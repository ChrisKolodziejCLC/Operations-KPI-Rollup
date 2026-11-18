/* Add identity-gated Operations KPI restricted drill-down result sets.

   The public wallboard remains aggregate-only and uses the default
   @IncludeRestrictedDetail = 0. Named employees and part-level rows are emitted
   only as result sets 16-20 when the separate restricted service explicitly
   opts in. The procedure remains read-only. This script is hash-gated and
   reversible.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @ExpectedOldHash varchar(64) = 'C61C9D839DCA1E82EE45186A9D0179110CB141C6A5B3C40D1213015332AD1608';
DECLARE @ExpectedNewHash varchar(64) = '9CF72B48DA59BBA526B0943F917793A020865D2C41DDDCA664BBB98850C970AF';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @OldDefinition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedOldHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@OldDefinition, N''))), 2);

IF @ObservedOldHash <> @ExpectedOldHash
    THROW 54301, 'Dashboard restricted drill-down migration pre-change hash mismatch.', 1;

DECLARE @ReviewedDefinition nvarchar(max) = N'/*
    Read-only historical rollup support for the QPTS Operations / Quality /
    Shipping report. Periods are intentionally coarse farther back and more
    detailed near the current report date:

      All prior year, Q1, Q2, prior months of the current quarter,
      prior weeks of the current month, then current-week days.

    This procedure does not write to QPTS data tables.
*/
CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup
    @ReportDateOverride date = NULL,
    @IncludeRestrictedDetail bit = 0
AS
BEGIN
    SET NOCOUNT ON;
    SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

    DECLARE @ReportDate date = COALESCE(@ReportDateOverride, DATEADD(day, -1, CONVERT(date, GETDATE())));
    -- The revised event-history method became authoritative on 2026-09-08.
    -- Do not blend earlier legacy event semantics into the new yield rollups.
    DECLARE @HistoryStart date = CONVERT(date, ''20260908'', 112);
    DECLARE @CurrentYearStart date = DATEFROMPARTS(YEAR(@ReportDate), 1, 1);
    DECLARE @MonthStart date = DATEFROMPARTS(YEAR(@ReportDate), MONTH(@ReportDate), 1);
    DECLARE @QuarterStart date = DATEFROMPARTS(YEAR(@ReportDate), (((MONTH(@ReportDate) - 1) / 3) * 3) + 1, 1);
    DECLARE @WeekStart date = DATEADD(day, -(DATEDIFF(day, CONVERT(date, ''19000107'', 112), @ReportDate) % 7), @ReportDate);
    DECLARE @WindowEndExclusive datetime2(0) = DATEADD(day, 1, CONVERT(datetime2(0), @ReportDate));
    DECLARE @FirstSundayAfterMonthStart date = DATEADD(
        day,
        (7 - (DATEDIFF(day, CONVERT(date, ''19000107'', 112), @MonthStart) % 7)) % 7,
        @MonthStart
    );

    SELECT
        h.id,
        h.part_id,
        h.PaintCart_ID,
        CONVERT(nvarchar(255), h.moment_category) AS moment_category,
        CONVERT(nvarchar(4000), h.moment_text) AS moment_text,
        CONVERT(nvarchar(255), h.user_name) AS user_name,
        CONVERT(nvarchar(100), h.defect_code) AS defect_code,
        CONVERT(date, h.moment_date) AS moment_date,
        CAST(h.moment_time AS time(3)) AS moment_time,
        DATEADD(
            millisecond,
            DATEDIFF(millisecond, CONVERT(time(3), ''00:00:00''), CAST(h.moment_time AS time(3))),
            CONVERT(datetime2(3), CONVERT(date, h.moment_date))
        ) AS moment_at
    INTO #HistoryAll
    FROM dbo.ritem_history_new AS h
    WHERE h.moment_date >= @HistoryStart
      AND h.moment_date < @WindowEndExclusive;

    CREATE INDEX IX_RollupHistoryAll_PartMoment ON #HistoryAll(part_id, moment_at, id);

    SELECT
        classified.part_id,
        CASE
            WHEN MAX(classified.is_service) = 1 THEN N''Svc''
            WHEN MAX(classified.is_bv) = 1 THEN N''BV''
            ELSE N''Prd''
        END AS part_class,
        MAX(classified.is_paint_scope) AS is_paint_scope,
        MAX(classified.is_n71_6164) AS is_n71_6164,
        MAX(classified.is_repaint_classified) AS is_repaint_classified,
        MAX(classified.color_key) AS color_key
    INTO #PartClass
    FROM (
        SELECT
            e.[Part ID] AS part_id,
            CASE WHEN ISNULL(e.Model, N'''') = N''Service'' THEN 1 ELSE 0 END AS is_service,
            CASE
                WHEN LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) = N''N33''
                  OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6171%'' THEN 1 ELSE 0
            END AS is_bv,
            CASE
                WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6164%'' THEN 1 ELSE 0
            END AS is_n71_6164,
            CASE
                WHEN CONVERT(nvarchar(8), e.[Origin]) = N''F'' OR ISNULL(e.Model, N'''') = N''Service'' THEN 1 ELSE 0
            END AS is_paint_scope,
            CASE
                WHEN CONVERT(nvarchar(255), e.insp_line_end_disposition) = N''Repaint''
                  OR CONVERT(nvarchar(255), e.repair_disposition) = N''WFP'' THEN 1 ELSE 0
            END AS is_repaint_classified,
            NULLIF(UPPER(LTRIM(RTRIM(CONVERT(nvarchar(255), e.[Color])))), N'''') AS color_key
        FROM dbo.[EDI Data Table] AS e
        WHERE e.[Part ID] IS NOT NULL
    ) AS classified
    GROUP BY classified.part_id;

    CREATE UNIQUE CLUSTERED INDEX IX_RollupPartClass_Part ON #PartClass(part_id);

    SELECT h.*
    INTO #History
    FROM #HistoryAll AS h
    INNER JOIN #PartClass AS pc ON pc.part_id = h.part_id
    WHERE pc.part_class <> N''Svc'';

    CREATE INDEX IX_RollupHistory_PartMoment ON #History(part_id, moment_at, id);

    /*
       Physical paint-pass contract.

       Item history links each part to a cart; tblCarts_Paint_Oven_Out supplies
       the authoritative pass timestamp. Master Data Table preserves the first
       EOL disposition. RepaintCount and load_line_repaint establish repaint
       ordinals without using mutable current disposition as first-pass truth.
    */
    SELECT
        m.ID AS part_id,
        NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), m.[Disposition EOL]))), N'''') AS first_disposition,
        COALESCE(m.RepaintCount, 0) AS repaint_count,
        CONVERT(datetime2(3), e.insp_line_end_stamp) AS current_eol_at,
        NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), e.insp_line_end_disposition))), N'''') AS current_disposition,
        pc.part_class,
        CASE
            WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Fender'' THEN N''FUKA''
            WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Bumper'' THEN N''Bumpers''
            WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Chassis Fairing'' THEN N''Fairings''
            ELSE N''Other''
        END AS repaint_line_set
    INTO #YieldParts
    FROM dbo.[Master Data Table] AS m
    INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = m.ID
    INNER JOIN #PartClass AS pc ON pc.part_id = m.ID
    WHERE pc.is_paint_scope = 1;

    CREATE UNIQUE CLUSTERED INDEX IX_RollupYieldParts_Part ON #YieldParts(part_id);

    SELECT
        h.part_id,
        h.PaintCart_ID,
        CONVERT(datetime2(3), MIN(oo.TimeStamp_Out)) AS oven_out_at
    INTO #PhysicalPassLinks
    FROM #HistoryAll AS h
    INNER JOIN #YieldParts AS yp ON yp.part_id = h.part_id
    INNER JOIN dbo.tblCarts_Paint_Oven_Out AS oo ON oo.Cart_ID_Out = h.PaintCart_ID
    WHERE h.moment_category = N''paint_oven_exited''
      AND h.PaintCart_ID IS NOT NULL
      AND h.PaintCart_ID > 0
      AND oo.TimeStamp_Out >= CONVERT(datetime2(0), @HistoryStart)
      AND oo.TimeStamp_Out < @WindowEndExclusive
    GROUP BY h.part_id, h.PaintCart_ID;

    CREATE UNIQUE CLUSTERED INDEX IX_RollupPhysicalPass_PartCart ON #PhysicalPassLinks(part_id, PaintCart_ID);

    ;WITH RepaintCartEvents AS (
        SELECT
            h.part_id,
            h.PaintCart_ID,
            MIN(h.moment_at) AS loaded_at
        FROM #HistoryAll AS h
        INNER JOIN #YieldParts AS yp ON yp.part_id = h.part_id
        WHERE h.moment_category = N''load_line_repaint''
          AND h.PaintCart_ID IS NOT NULL
          AND h.PaintCart_ID > 0
        GROUP BY h.part_id, h.PaintCart_ID
    ), RankedRepaintLinks AS (
        SELECT
            r.part_id,
            r.PaintCart_ID,
            r.loaded_at,
            p.oven_out_at,
            ROW_NUMBER() OVER (
                PARTITION BY r.part_id
                ORDER BY r.loaded_at, r.PaintCart_ID
            ) AS loop_ordinal
        FROM RepaintCartEvents AS r
        INNER JOIN #PhysicalPassLinks AS p
            ON p.part_id = r.part_id
           AND p.PaintCart_ID = r.PaintCart_ID
        WHERE p.oven_out_at >= r.loaded_at
    )
    SELECT
        r.part_id,
        r.PaintCart_ID,
        r.oven_out_at,
        r.loop_ordinal
    INTO #RepaintPassLinks
    FROM RankedRepaintLinks AS r;

    CREATE UNIQUE CLUSTERED INDEX IX_RollupRepaintPass_PartCart ON #RepaintPassLinks(part_id, PaintCart_ID);

    ;WITH RankedPhysicalPasses AS (
        SELECT
            p.part_id,
            p.PaintCart_ID,
            p.oven_out_at,
            ROW_NUMBER() OVER (
                PARTITION BY p.part_id
                ORDER BY p.oven_out_at, p.PaintCart_ID
            ) AS gp_pass_ordinal,
            COUNT(*) OVER (PARTITION BY p.part_id) AS gp_pass_count
        FROM #PhysicalPassLinks AS p
    ), BaseClassifiedPasses AS (
        SELECT
            p.part_id,
            p.PaintCart_ID,
            p.oven_out_at,
            p.gp_pass_ordinal,
            p.gp_pass_count,
            yp.current_eol_at,
            yp.current_disposition,
            yp.part_class,
            yp.repaint_line_set,
            q.local_disposition,
            CASE WHEN r.part_id IS NULL THEN 1 ELSE 0 END AS is_initial_pass,
            CASE WHEN r.part_id IS NULL THEN 0 ELSE 1 END AS is_repaint_loop,
            CASE WHEN r.loop_ordinal = 1 THEN 1 ELSE 0 END AS is_first_repaint_loop,
            CASE
                WHEN r.part_id IS NULL THEN yp.first_disposition
                WHEN r.loop_ordinal < yp.repaint_count THEN N''Repaint''
                WHEN r.loop_ordinal = yp.repaint_count AND yp.current_eol_at >= p.oven_out_at THEN yp.current_disposition
                ELSE NULL
            END AS pass_disposition
        FROM RankedPhysicalPasses AS p
        INNER JOIN #YieldParts AS yp ON yp.part_id = p.part_id
        LEFT JOIN #RepaintPassLinks AS r
            ON r.part_id = p.part_id
           AND r.PaintCart_ID = p.PaintCart_ID
        OUTER APPLY (
            SELECT TOP (1)
                CASE h.moment_category
                    WHEN N''end_of_line_approved'' THEN N''Approved''
                    WHEN N''end_of_line_repair'' THEN N''Repair''
                    WHEN N''end_of_line_repaint'' THEN N''Repaint''
                    WHEN N''end_of_line_direct_repaint'' THEN N''Direct Repaint''
                    WHEN N''end_of_line_reject'' THEN N''Reject''
                END AS local_disposition
            FROM #HistoryAll AS h
            WHERE h.part_id = p.part_id
              AND h.PaintCart_ID = p.PaintCart_ID
              AND h.moment_at >= p.oven_out_at
              AND h.moment_category IN (
                  N''end_of_line_approved'',
                  N''end_of_line_repair'',
                  N''end_of_line_repaint'',
                  N''end_of_line_direct_repaint'',
                  N''end_of_line_reject''
              )
            ORDER BY h.moment_at, h.id
        ) AS q
    ), ClassifiedPasses AS (
        SELECT
            b.*,
            CASE
                WHEN b.part_class = N''BV'' AND b.gp_pass_ordinal = 1 THEN 1
                WHEN b.part_class = N''BV'' THEN 0
                ELSE b.is_initial_pass
            END AS repaint_is_initial_pass,
            CASE
                WHEN b.part_class = N''BV'' AND b.gp_pass_ordinal < b.gp_pass_count THEN 1
                WHEN b.part_class = N''BV'' AND COALESCE(
                    b.local_disposition,
                    CASE WHEN b.current_eol_at >= b.oven_out_at THEN b.current_disposition END
                ) IN (N''Repaint'', N''Direct Repaint'') THEN 1
                WHEN b.part_class = N''BV'' THEN 0
                WHEN b.pass_disposition IN (N''Repaint'', N''Direct Repaint'') THEN 1
                ELSE 0
            END AS repaint_is_failure,
            CASE
                WHEN b.part_class = N''BV'' AND b.gp_pass_ordinal < b.gp_pass_count THEN 0
                WHEN b.part_class = N''BV'' AND COALESCE(
                    b.local_disposition,
                    CASE WHEN b.current_eol_at >= b.oven_out_at THEN b.current_disposition END
                ) IS NULL THEN 1
                WHEN b.part_class = N''BV'' THEN 0
                WHEN b.pass_disposition IS NULL THEN 1
                ELSE 0
            END AS repaint_is_pending
        FROM BaseClassifiedPasses AS b
    )
    SELECT
        part_id,
        PaintCart_ID,
        CONVERT(date, oven_out_at) AS event_date,
        oven_out_at AS event_at,
        part_class,
        repaint_line_set,
        is_initial_pass,
        is_repaint_loop,
        is_first_repaint_loop,
        repaint_is_initial_pass,
        repaint_is_failure,
        repaint_is_pending,
        CASE WHEN pass_disposition IN (N''Repaint'', N''Direct Repaint'') THEN 1 ELSE 0 END AS is_repaint_failure,
        CASE WHEN pass_disposition = N''Repair'' THEN 1 ELSE 0 END AS is_finesse_repair,
        CASE WHEN pass_disposition = N''Approved'' THEN 1 ELSE 0 END AS is_eol_approved,
        CASE WHEN pass_disposition IS NOT NULL AND pass_disposition <> N''Approved'' THEN 1 ELSE 0 END AS is_eol_reject,
        CASE WHEN pass_disposition IS NULL THEN 1 ELSE 0 END AS is_eol_pending
    INTO #PaintPasses
    FROM ClassifiedPasses;

    CREATE INDEX IX_RollupPaintDate ON #PaintPasses(event_date, part_id);

    /*
       First receiving decision per part. Finesse follows rejected parts from
       that immutable cohort even when repaint later changes current Origin.
    */
    WITH FirstReceiving AS (
        SELECT
            h.part_id,
            h.moment_date,
            h.moment_category,
            CASE
                WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Fender'' THEN N''FUKA''
                WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Bumper'' THEN N''Bumpers''
                WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Chassis Fairing'' THEN N''Fairings''
                ELSE N''Other''
            END AS inspection_line_set,
            CASE
                WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.repair_disposition))) = N''Repaired'' THEN N''Repaired''
                WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.repair_disposition))) = N''WFP''
                  OR LTRIM(RTRIM(CONVERT(nvarchar(255), e.insp_line_end_disposition))) = N''Repaint'' THEN N''Repaint''
                ELSE N''Pending''
            END AS finesse_outcome,
            ROW_NUMBER() OVER (PARTITION BY h.part_id ORDER BY h.moment_at, h.id) AS rn
        FROM #History AS h
        INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = h.part_id
        WHERE h.moment_category IN (N''receiving_approved'', N''receiving_reject'')
    )
    SELECT
        moment_date AS event_date,
        COUNT(*) AS receiving_total,
        SUM(CASE WHEN moment_category = N''receiving_approved'' THEN 1 ELSE 0 END) AS receiving_approved,
        SUM(CASE WHEN inspection_line_set = N''Bumpers'' THEN 1 ELSE 0 END) AS receiving_bumper_total,
        SUM(CASE WHEN inspection_line_set = N''Bumpers'' AND moment_category = N''receiving_approved'' THEN 1 ELSE 0 END) AS receiving_bumper_approved,
        SUM(CASE WHEN inspection_line_set = N''Fairings'' THEN 1 ELSE 0 END) AS receiving_fairing_total,
        SUM(CASE WHEN inspection_line_set = N''Fairings'' AND moment_category = N''receiving_approved'' THEN 1 ELSE 0 END) AS receiving_fairing_approved,
        SUM(CASE WHEN moment_category = N''receiving_reject'' THEN 1 ELSE 0 END) AS finesse_rejected_count,
        SUM(CASE WHEN moment_category = N''receiving_reject'' AND finesse_outcome = N''Repaired'' THEN 1 ELSE 0 END) AS finesse_repair_count,
        SUM(CASE WHEN moment_category = N''receiving_reject'' AND finesse_outcome = N''Repaint'' THEN 1 ELSE 0 END) AS finesse_repaint_count,
        SUM(CASE WHEN moment_category = N''receiving_reject'' AND finesse_outcome = N''Pending'' THEN 1 ELSE 0 END) AS finesse_pending_count,
        SUM(CASE WHEN moment_category = N''receiving_reject'' AND finesse_outcome = N''Repaired'' AND inspection_line_set = N''Bumpers'' THEN 1 ELSE 0 END) AS bumper_finesse_repair_count,
        SUM(CASE WHEN moment_category = N''receiving_reject'' AND finesse_outcome = N''Repaired'' AND inspection_line_set = N''Fairings'' THEN 1 ELSE 0 END) AS fairing_finesse_repair_count,
        SUM(CASE WHEN moment_category = N''receiving_reject'' AND finesse_outcome = N''Repaired'' AND inspection_line_set NOT IN (N''Bumpers'', N''Fairings'') THEN 1 ELSE 0 END) AS other_finesse_repair_count
    INTO #ReceivingFirst
    FROM FirstReceiving
    WHERE rn = 1
    GROUP BY moment_date;

    /* First final-inspection decision per part, split by product family. */
    WITH FirstFinal AS (
        SELECT
            h.part_id,
            h.moment_date,
            h.moment_category,
            CASE
                WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Fender'' THEN N''FUKA''
                WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Bumper'' THEN N''Bumpers''
                WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Chassis Fairing'' THEN N''Fairings''
                ELSE N''Other''
            END AS inspection_line_set,
            ROW_NUMBER() OVER (PARTITION BY h.part_id ORDER BY h.moment_at, h.id) AS rn
        FROM #History AS h
        INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = h.part_id
        WHERE h.moment_category IN (N''final_approved'', N''final_reject'')
    )
    SELECT
        moment_date AS event_date,
        COUNT(*) AS final_total,
        SUM(CASE WHEN moment_category = N''final_approved'' THEN 1 ELSE 0 END) AS final_approved,
        SUM(CASE WHEN inspection_line_set = N''FUKA'' THEN 1 ELSE 0 END) AS final_fuka_total,
        SUM(CASE WHEN inspection_line_set = N''FUKA'' AND moment_category = N''final_approved'' THEN 1 ELSE 0 END) AS final_fuka_approved,
        SUM(CASE WHEN inspection_line_set = N''Bumpers'' THEN 1 ELSE 0 END) AS final_bumper_total,
        SUM(CASE WHEN inspection_line_set = N''Bumpers'' AND moment_category = N''final_approved'' THEN 1 ELSE 0 END) AS final_bumper_approved,
        SUM(CASE WHEN inspection_line_set = N''Fairings'' THEN 1 ELSE 0 END) AS final_fairing_total,
        SUM(CASE WHEN inspection_line_set = N''Fairings'' AND moment_category = N''final_approved'' THEN 1 ELSE 0 END) AS final_fairing_approved
    INTO #FinalFirst
    FROM FirstFinal
    WHERE rn = 1
    GROUP BY moment_date;

    /* Materialize classified event grains once for the historical rollup. */
    SELECT
        h.moment_date AS report_date,
        h.part_id,
        h.PaintCart_ID,
        h.moment_at,
        pc.part_class,
        pc.is_n71_6164,
        pc.color_key
    INTO #PaintExitEvents
    FROM #HistoryAll AS h
    INNER JOIN #PartClass AS pc ON pc.part_id = h.part_id
    WHERE h.moment_category = N''paint_oven_exited''
      AND h.PaintCart_ID IS NOT NULL
      AND h.PaintCart_ID > 0
      AND pc.is_paint_scope = 1;

    CREATE INDEX IX_RollupPaintExitEvents_DateCart ON #PaintExitEvents(report_date, PaintCart_ID);

    SELECT
        report_date,
        PaintCart_ID,
        CASE
            WHEN MAX(CASE WHEN part_class = N''Svc'' THEN 1 ELSE 0 END) = 1 THEN N''Svc''
            WHEN MAX(CASE WHEN part_class = N''BV'' THEN 1 ELSE 0 END) = 1 THEN N''BV''
            ELSE N''Prd''
        END AS cart_class,
        CASE
            WHEN MAX(CASE WHEN part_class = N''Svc'' THEN 1 ELSE 0 END) = 0
             AND MAX(CASE WHEN part_class = N''BV'' THEN 1 ELSE 0 END) = 0
             AND MAX(is_n71_6164) = 1 THEN 1 ELSE 0
        END AS is_n71_6164_cart
    INTO #PaintCartClasses
    FROM #PaintExitEvents
    GROUP BY report_date, PaintCart_ID;

    CREATE UNIQUE CLUSTERED INDEX IX_RollupPaintCartClasses_DateCart ON #PaintCartClasses(report_date, PaintCart_ID);

    SELECT
        h.moment_date AS report_date,
        h.moment_at AS loaded_at,
        h.part_id,
        h.PaintCart_ID,
        pc.part_class,
        pc.is_n71_6164,
        pc.color_key
    INTO #LoadedEvents
    FROM #HistoryAll AS h
    INNER JOIN #PartClass AS pc ON pc.part_id = h.part_id
    WHERE h.moment_category IN (N''load_line'', N''load_line_repaint'');

    CREATE INDEX IX_RollupLoadedEvents_DateCart ON #LoadedEvents(report_date, PaintCart_ID);

    SELECT
        report_date,
        PaintCart_ID,
        CASE
            WHEN MAX(CASE WHEN part_class = N''Svc'' THEN 1 ELSE 0 END) = 1 THEN N''Svc''
            WHEN MAX(CASE WHEN part_class = N''BV'' THEN 1 ELSE 0 END) = 1 THEN N''BV''
            ELSE N''Prd''
        END AS cart_class,
        CASE
            WHEN MAX(CASE WHEN part_class = N''Svc'' THEN 1 ELSE 0 END) = 0
             AND MAX(CASE WHEN part_class = N''BV'' THEN 1 ELSE 0 END) = 0
             AND MAX(is_n71_6164) = 1 THEN 1 ELSE 0
        END AS is_n71_6164_cart
    INTO #LoadedCartClasses
    FROM #LoadedEvents
    WHERE PaintCart_ID IS NOT NULL
    GROUP BY report_date, PaintCart_ID;

    CREATE UNIQUE CLUSTERED INDEX IX_RollupLoadedCartClasses_DateCart ON #LoadedCartClasses(report_date, PaintCart_ID);

    /* One daily grain powers every historical period. */
    ;WITH DateRange AS (
        SELECT @HistoryStart AS report_date
        UNION ALL
        SELECT DATEADD(day, 1, report_date)
        FROM DateRange
        WHERE report_date < @ReportDate
    ), ScheduleDaily AS (
        SELECT
            CONVERT(date, [Production Date]) AS report_date,
            MAX([Pieces Scheduled]) AS pieces_scheduled,
            MAX([Hours Scheduled]) AS hours_scheduled
        FROM dbo.[Production Schedule]
        WHERE [Production Date] >= CONVERT(datetime2(0), @HistoryStart)
          AND [Production Date] < @WindowEndExclusive
        GROUP BY CONVERT(date, [Production Date])
    ), PaintExitDaily AS (
        SELECT
            pe.report_date,
            COUNT(DISTINCT pe.PaintCart_ID) AS paint_processed,
            COUNT(DISTINCT CASE WHEN pc.cart_class = N''Prd'' THEN pe.PaintCart_ID END) AS production_paint_carts,
            COUNT(DISTINCT CASE WHEN pc.cart_class = N''BV'' THEN pe.PaintCart_ID END) AS bv_paint_carts,
            COUNT(DISTINCT CASE WHEN pc.cart_class = N''Svc'' THEN pe.PaintCart_ID END) AS service_paint_carts,
            COUNT(DISTINCT CASE WHEN pc.cart_class = N''Prd'' AND pc.is_n71_6164_cart = 1 THEN pe.PaintCart_ID END) AS n71_6164_paint_carts,
            COUNT(*) AS paint_pieces_processed,
            SUM(CASE WHEN pe.part_class = N''Prd'' THEN 1 ELSE 0 END) AS production_paint_pieces_processed,
            SUM(CASE WHEN pe.part_class = N''BV'' THEN 1 ELSE 0 END) AS bv_paint_pieces_processed,
            SUM(CASE WHEN pe.part_class = N''Svc'' THEN 1 ELSE 0 END) AS service_paint_pieces_processed,
            SUM(CASE WHEN pe.part_class = N''Prd'' AND pe.is_n71_6164 = 1 THEN 1 ELSE 0 END) AS n71_6164_paint_pieces_processed,
            COUNT(DISTINCT pe.part_id) AS unique_pieces_processed,
            COUNT(DISTINCT DATEPART(hour, pe.moment_at)) AS paint_hours
        FROM #PaintExitEvents AS pe
        INNER JOIN #PaintCartClasses AS pc
            ON pc.report_date = pe.report_date
           AND pc.PaintCart_ID = pe.PaintCart_ID
        GROUP BY pe.report_date
    ), PaintDaily AS (
        SELECT
            p.event_date AS report_date,
            COUNT(*) AS paint_decision_pieces,
            SUM(CASE WHEN p.part_class = N''Prd'' THEN 1 ELSE 0 END) AS production_paint_decision_pieces,
            SUM(CASE WHEN p.part_class = N''BV'' THEN 1 ELSE 0 END) AS bv_paint_decision_pieces,
            SUM(CASE WHEN p.part_class = N''Svc'' THEN 1 ELSE 0 END) AS service_paint_decision_pieces,
            SUM(CASE WHEN p.repaint_is_pending = 0 AND p.repaint_is_failure = 0 THEN 1 ELSE 0 END) AS ppy_approved,
            SUM(CASE WHEN p.part_class = N''Prd'' AND p.repaint_is_pending = 0 AND p.repaint_is_failure = 0 THEN 1 ELSE 0 END) AS production_ppy_approved,
            SUM(CASE WHEN p.part_class = N''BV'' AND p.repaint_is_pending = 0 AND p.repaint_is_failure = 0 THEN 1 ELSE 0 END) AS bv_ppy_approved,
            SUM(CASE WHEN p.part_class = N''Svc'' AND p.repaint_is_pending = 0 AND p.repaint_is_failure = 0 THEN 1 ELSE 0 END) AS service_ppy_approved,
            SUM(p.repaint_is_failure) AS ppy_repaint_count,
            SUM(p.repaint_is_pending) AS repaint_ppy_pending_count,
            SUM(p.repaint_is_initial_pass) AS paint_fty_total,
            SUM(CASE WHEN p.part_class = N''Prd'' THEN p.repaint_is_initial_pass ELSE 0 END) AS production_paint_fty_total,
            SUM(CASE WHEN p.part_class = N''BV'' THEN p.repaint_is_initial_pass ELSE 0 END) AS bv_paint_fty_total,
            SUM(CASE WHEN p.part_class = N''Svc'' THEN p.repaint_is_initial_pass ELSE 0 END) AS service_paint_fty_total,
            SUM(CASE WHEN p.repaint_is_initial_pass = 1 AND p.repaint_is_pending = 0 AND p.repaint_is_failure = 0 THEN 1 ELSE 0 END) AS paint_fty_approved,
            SUM(CASE WHEN p.part_class = N''Prd'' AND p.repaint_is_initial_pass = 1 AND p.repaint_is_pending = 0 AND p.repaint_is_failure = 0 THEN 1 ELSE 0 END) AS production_paint_fty_approved,
            SUM(CASE WHEN p.part_class = N''BV'' AND p.repaint_is_initial_pass = 1 AND p.repaint_is_pending = 0 AND p.repaint_is_failure = 0 THEN 1 ELSE 0 END) AS bv_paint_fty_approved,
            SUM(CASE WHEN p.part_class = N''Svc'' AND p.repaint_is_initial_pass = 1 AND p.repaint_is_pending = 0 AND p.repaint_is_failure = 0 THEN 1 ELSE 0 END) AS service_paint_fty_approved,
            SUM(CASE WHEN p.repaint_is_initial_pass = 1 THEN p.repaint_is_failure ELSE 0 END) AS paint_fty_repaint_count,
            SUM(CASE WHEN p.repaint_is_initial_pass = 1 THEN p.repaint_is_pending ELSE 0 END) AS repaint_fty_pending_count,
            SUM(CASE WHEN p.repaint_is_initial_pass = 1 AND p.repaint_is_failure = 1 AND p.repaint_line_set = N''FUKA'' THEN 1 ELSE 0 END) AS fuka_paint_fty_repaint_count,
            SUM(CASE WHEN p.repaint_is_initial_pass = 1 AND p.repaint_is_failure = 1 AND p.repaint_line_set = N''Bumpers'' THEN 1 ELSE 0 END) AS bumper_paint_fty_repaint_count,
            SUM(CASE WHEN p.repaint_is_initial_pass = 1 AND p.repaint_is_failure = 1 AND p.repaint_line_set = N''Fairings'' THEN 1 ELSE 0 END) AS fairing_paint_fty_repaint_count,
            SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_finesse_repair ELSE 0 END) AS paint_fty_repair_count,
            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_finesse_repair = 1 AND p.repaint_line_set = N''FUKA'' THEN 1 ELSE 0 END) AS fuka_paint_fty_repair_count,
            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_finesse_repair = 1 AND p.repaint_line_set = N''Fairings'' THEN 1 ELSE 0 END) AS fairing_paint_fty_repair_count,
            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_finesse_repair = 1 AND p.repaint_line_set = N''Bumpers'' THEN 1 ELSE 0 END) AS bumper_paint_fty_repair_count,
            COUNT(*) AS reject_ppy_total,
            SUM(p.is_eol_approved) AS reject_ppy_approved,
            SUM(p.is_eol_reject) AS reject_ppy_rejected_count,
            SUM(p.is_eol_pending) AS reject_ppy_pending_count,
            SUM(p.is_initial_pass) AS reject_fty_total,
            SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_eol_approved ELSE 0 END) AS reject_fty_approved,
            SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_eol_reject ELSE 0 END) AS reject_fty_rejected_count,
            SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_eol_pending ELSE 0 END) AS reject_fty_pending_count
        FROM #PaintPasses AS p
        GROUP BY p.event_date
    ), LoadedDaily AS (
        SELECT
            le.report_date,
            COUNT(*) AS parts_loaded,
            SUM(CASE WHEN le.part_class = N''Prd'' THEN 1 ELSE 0 END) AS production_parts_loaded,
            SUM(CASE WHEN le.part_class = N''BV'' THEN 1 ELSE 0 END) AS bv_parts_loaded,
            SUM(CASE WHEN le.part_class = N''Svc'' THEN 1 ELSE 0 END) AS service_parts_loaded,
            SUM(CASE WHEN le.part_class = N''Prd'' AND le.is_n71_6164 = 1 THEN 1 ELSE 0 END) AS n71_6164_parts_loaded,
            COUNT(DISTINCT le.part_id) AS unique_pieces_loaded,
            COUNT(DISTINCT le.PaintCart_ID) AS carts_loaded,
            COUNT(DISTINCT CASE WHEN lc.cart_class = N''Prd'' THEN le.PaintCart_ID END) AS production_carts_loaded,
            COUNT(DISTINCT CASE WHEN lc.cart_class = N''BV'' THEN le.PaintCart_ID END) AS bv_carts_loaded,
            COUNT(DISTINCT CASE WHEN lc.cart_class = N''Svc'' THEN le.PaintCart_ID END) AS service_carts_loaded,
            COUNT(DISTINCT CASE WHEN lc.cart_class = N''Prd'' AND lc.is_n71_6164_cart = 1 THEN le.PaintCart_ID END) AS n71_6164_carts_loaded
        FROM #LoadedEvents AS le
        LEFT JOIN #LoadedCartClasses AS lc
            ON lc.report_date = le.report_date
           AND lc.PaintCart_ID = le.PaintCart_ID
        GROUP BY le.report_date
    ), EolDaily AS (
        SELECT
            h.moment_date AS report_date,
            COUNT(DISTINCT h.part_id) AS eol_inspected
        FROM #History AS h
        INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = h.part_id AND ISNULL(e.Model, N'''') <> N''Service''
        WHERE h.moment_category IN (N''end_of_line_approved'', N''end_of_line_repair'', N''end_of_line_repaint'', N''end_of_line_direct_repaint'', N''end_of_line_reject'')
        GROUP BY h.moment_date
    ), ShipDaily AS (
        SELECT
            CONVERT(date, e.ship_date) AS report_date,
            COUNT(DISTINCT e.[Part ID]) AS parts_shipped,
            COUNT(DISTINCT CASE WHEN CONVERT(nvarchar(10), e.Origin) = N''F'' THEN e.[Part ID] END) AS painted_parts_shipped,
            COUNT(DISTINCT CASE WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Bumper'' THEN e.[Part ID] END) AS bumpers_shipped
        FROM dbo.[EDI Data Table] AS e
        WHERE e.ship_status = N''SHIPPED''
          AND e.ship_date >= CONVERT(datetime2(0), @HistoryStart)
          AND e.ship_date < @WindowEndExclusive
          AND ISNULL(e.Model, N'''') <> N''Service''
        GROUP BY CONVERT(date, e.ship_date)
    ), AssemblyDaily AS (
        SELECT
            assembled.report_date,
            COUNT(DISTINCT assembled.part_id) AS parts_assembled,
            COUNT(DISTINCT CASE WHEN assembled.is_bumper = 1 THEN assembled.part_id END) AS assembled_bumper_count,
            COUNT(DISTINCT CASE WHEN assembled.is_bumper = 1 AND assembled.is_mic = 1 THEN assembled.part_id END) AS mic_assembled_bumper_count,
            COUNT(DISTINCT CASE WHEN assembled.is_bumper = 1 AND assembled.is_mic = 0 THEN assembled.part_id END) AS painted_assembled_bumper_count
        FROM (
            SELECT
                CONVERT(date, e.AssembledDate) AS report_date,
                e.[Part ID] AS part_id,
                CASE WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6171%'' THEN 1 ELSE 0 END AS is_bumper,
                CASE WHEN UPPER(LTRIM(RTRIM(CONVERT(nvarchar(255), e.Color)))) = N''MIC'' THEN 1 ELSE 0 END AS is_mic
            FROM dbo.[EDI Data Table] AS e
            WHERE e.AssembledDate >= CONVERT(datetime2(0), @HistoryStart)
              AND e.AssembledDate < @WindowEndExclusive
              AND ISNULL(e.Model, N'''') <> N''Service''
              AND LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) IN (N''N33'', N''N35'', N''N71'')
        ) AS assembled
        GROUP BY assembled.report_date
    ), CompleteAssemblyDaily AS (
        SELECT
            complete_sets.report_date,
            COUNT(*) AS complete_assy_sets,
            SUM(complete_sets.is_mic_set) AS mic_complete_assy_sets,
            SUM(1 - complete_sets.is_mic_set) AS painted_complete_assy_sets
        FROM (
            SELECT
                MAX(CONVERT(date, e.AssembledDate)) AS report_date,
                CONVERT(nvarchar(255), e.[Sequence]) AS sequence_id,
                CASE WHEN COUNT(DISTINCT CASE
                    WHEN UPPER(LTRIM(RTRIM(CONVERT(nvarchar(255), e.Color)))) = N''MIC'' THEN e.[Part ID]
                END) = 4 THEN 1 ELSE 0 END AS is_mic_set
            FROM dbo.[EDI Data Table] AS e
            WHERE e.AssembledDate IS NOT NULL
              AND e.AssembledDate < @WindowEndExclusive
              AND ISNULL(e.Model, N'''') <> N''Service''
              AND (
                  LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) = N''N33''
                  OR LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Chassis Fairing''
              )
              AND NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), e.[Sequence]))), N'''') IS NOT NULL
            GROUP BY CONVERT(nvarchar(255), e.[Sequence])
            HAVING COUNT(DISTINCT e.[Part ID]) = 4
        ) AS complete_sets
        WHERE complete_sets.report_date >= @HistoryStart
        GROUP BY complete_sets.report_date
    ), ReceivingQuantityDaily AS (
        SELECT
            CONVERT(date, e.insp_receive_stamp) AS report_date,
            COUNT(DISTINCT e.[Part ID]) AS receiving_quantity
        FROM dbo.[EDI Data Table] AS e
        WHERE e.insp_receive_stamp >= CONVERT(datetime2(0), @HistoryStart)
          AND e.insp_receive_stamp < @WindowEndExclusive
          AND ISNULL(e.Model, N'''') <> N''Service''
        GROUP BY CONVERT(date, e.insp_receive_stamp)
    ), FinalQuantityDaily AS (
        SELECT
            CONVERT(date, e.insp_final_stamp) AS report_date,
            COUNT(DISTINCT e.[Part ID]) AS final_quantity
        FROM dbo.[EDI Data Table] AS e
        WHERE e.insp_final_stamp >= CONVERT(datetime2(0), @HistoryStart)
          AND e.insp_final_stamp < @WindowEndExclusive
          AND ISNULL(e.Model, N'''') <> N''Service''
        GROUP BY CONVERT(date, e.insp_final_stamp)
    ), ReceivingOutcomeDaily AS (
        SELECT
            h.moment_date AS report_date,
            COUNT(DISTINCT CASE
                WHEN CONVERT(nvarchar(255), e.insp_line_end_disposition) = N''Repair''
                 AND ISNULL(CONVERT(nvarchar(255), e.repair_disposition), N'''') <> N''WFP''
                THEN h.part_id END) AS receiving_repair_qty,
            COUNT(DISTINCT CASE
                WHEN CONVERT(nvarchar(255), e.insp_line_end_disposition) = N''Repaint''
                  OR CONVERT(nvarchar(255), e.repair_disposition) = N''WFP''
                THEN h.part_id END) AS receiving_repaint_qty
        FROM #History AS h
        INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = h.part_id
        WHERE h.moment_category = N''receiving_reject''
        GROUP BY h.moment_date
    ), TrailerContents AS (
        SELECT
            CONVERT(date, e.ship_date) AS report_date,
            LTRIM(RTRIM(e.ship_trailer)) AS trailer_id,
            SUM(CASE WHEN CONVERT(nvarchar(255), e.Description) = N''Fender'' THEN 1 ELSE 0 END) AS fender_parts,
            SUM(CASE WHEN CONVERT(nvarchar(255), e.Description) = N''Bumper'' THEN 1 ELSE 0 END) AS bumper_parts,
            SUM(CASE WHEN CONVERT(nvarchar(255), e.Description) = N''Chassis Fairing'' THEN 1 ELSE 0 END) AS fairing_parts
        FROM dbo.[EDI Data Table] AS e
        WHERE e.ship_date >= CONVERT(datetime2(0), @HistoryStart)
          AND e.ship_date < @WindowEndExclusive
          AND ISNULL(e.Model, N'''') <> N''Service''
          AND NULLIF(LTRIM(RTRIM(e.ship_trailer)), N'''') IS NOT NULL
        GROUP BY CONVERT(date, e.ship_date), LTRIM(RTRIM(e.ship_trailer))
    ), TrailerClasses AS (
        SELECT
            report_date,
            trailer_id,
            CASE
                WHEN fender_parts >= bumper_parts AND fender_parts >= fairing_parts AND fender_parts > 0 THEN N''FUKA''
                WHEN bumper_parts >= fairing_parts AND bumper_parts > 0 THEN N''Bumpers''
                WHEN fairing_parts > 0 THEN N''Fairings''
                ELSE N''Other''
            END AS trailer_type
        FROM TrailerContents
    ), TrailerDaily AS (
        SELECT
            report_date,
            COUNT(*) AS trailers_prepared,
            SUM(CASE WHEN trailer_type = N''FUKA'' THEN 1 ELSE 0 END) AS fuka_trailers_prepared,
            SUM(CASE WHEN trailer_type = N''Bumpers'' THEN 1 ELSE 0 END) AS bumper_trailers_prepared,
            SUM(CASE WHEN trailer_type = N''Fairings'' THEN 1 ELSE 0 END) AS fairing_trailers_prepared,
            SUM(CASE WHEN trailer_type = N''Other'' THEN 1 ELSE 0 END) AS other_trailers_prepared
        FROM TrailerClasses
        GROUP BY report_date
    ), RackContents AS (
        SELECT
            CONVERT(date, e.ship_date) AS report_date,
            LTRIM(RTRIM(CONVERT(nvarchar(255), e.Rack))) AS rack_id,
            SUM(CASE WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6164%'' THEN 1 ELSE 0 END) AS n71_6164_parts,
            SUM(CASE
                WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6164%'' THEN 0
                WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Fender'' THEN 1 ELSE 0
            END) AS fuka_parts,
            SUM(CASE
                WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6164%'' THEN 0
                WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Bumper'' THEN 1 ELSE 0
            END) AS bumper_parts,
            SUM(CASE
                WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6164%'' THEN 0
                WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Chassis Fairing'' THEN 1 ELSE 0
            END) AS fairing_parts
        FROM dbo.[EDI Data Table] AS e
        WHERE e.ship_date >= CONVERT(datetime2(0), @HistoryStart)
          AND e.ship_date < @WindowEndExclusive
          AND CONVERT(nvarchar(255), e.ship_status) = N''SHIPPED''
          AND ISNULL(e.Model, N'''') <> N''Service''
          AND NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), e.Rack))), N'''') IS NOT NULL
        GROUP BY CONVERT(date, e.ship_date), LTRIM(RTRIM(CONVERT(nvarchar(255), e.Rack)))
    ), RackClasses AS (
        SELECT
            report_date,
            rack_id,
            CASE
                WHEN n71_6164_parts >= fuka_parts AND n71_6164_parts >= bumper_parts AND n71_6164_parts >= fairing_parts AND n71_6164_parts > 0 THEN N''N71-6164''
                WHEN fuka_parts >= bumper_parts AND fuka_parts >= fairing_parts AND fuka_parts > 0 THEN N''FUKA''
                WHEN bumper_parts >= fairing_parts AND bumper_parts > 0 THEN N''Bumpers''
                WHEN fairing_parts > 0 THEN N''Fairings''
                ELSE N''Other''
            END AS rack_type
        FROM RackContents
    ), RackDaily AS (
        SELECT
            report_date,
            COUNT(*) AS racks_shipped,
            SUM(CASE WHEN rack_type = N''FUKA'' THEN 1 ELSE 0 END) AS fuka_racks_shipped,
            SUM(CASE WHEN rack_type = N''Bumpers'' THEN 1 ELSE 0 END) AS bumper_racks_shipped,
            SUM(CASE WHEN rack_type = N''N71-6164'' THEN 1 ELSE 0 END) AS n71_6164_racks_shipped,
            SUM(CASE WHEN rack_type = N''Fairings'' THEN 1 ELSE 0 END) AS fairing_racks_shipped,
            SUM(CASE WHEN rack_type = N''Other'' THEN 1 ELSE 0 END) AS other_racks_shipped
        FROM RackClasses
        GROUP BY report_date
    ), TrailerDepartureDaily AS (
        SELECT
            CONVERT(date, d.TimeOut) AS report_date,
            COUNT_BIG(*) AS trailers_shipped
        FROM dbo.DriverLog AS d
        WHERE d.TimeOut >= CONVERT(datetime2(0), @HistoryStart)
          AND d.TimeOut < @WindowEndExclusive
          AND NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), d.TrailerID))), N'''') IS NOT NULL
        GROUP BY CONVERT(date, d.TimeOut)
    ), StagedRepaintCarts AS (
        SELECT DISTINCT e.cart_id
        FROM dbo.[EDI Data Table] AS e
        INNER JOIN dbo.[Master Data Table] AS m ON m.ID = e.[Part ID]
        LEFT JOIN dbo.tblCarts_Paint AS cp
            ON cp.[Cart ID] = e.cart_id
           AND cp.[Time Stamp] < @WindowEndExclusive
        WHERE e.cart_id IS NOT NULL
          AND e.Origin = N''F''
          AND cp.[Cart ID] IS NULL
          AND ISNULL(LTRIM(RTRIM(e.[Color])), N'''') <> N''''
          AND e.[Paint Block] NOT LIKE N''Arc%''
          AND ISNULL(m.RepaintCount, 0) > 0
          AND (e.insp_line_end_disposition IS NULL OR e.insp_line_end_disposition <> N''Approved'')
          AND e.cart_load_verified_stamp >= DATEADD(day, -6, CONVERT(datetime2(0), @ReportDate))
          AND e.cart_load_verified_stamp < @WindowEndExclusive
    ), StagedEligibleParts AS (
        SELECT
            LEFT(e.[Paint Block], 3) AS block_id,
            e.cart_id,
            e.cart_load_verified_stamp AS loaded_stamp,
            CASE
                WHEN ISNULL(e.Model, N'''') = N''Service'' THEN N''Svc''
                WHEN LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) = N''N33''
                  OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6171%'' THEN N''BV''
                ELSE N''Prd''
            END AS part_class,
            CASE WHEN rc.cart_id IS NULL THEN 0 ELSE 1 END AS has_repaint
        FROM dbo.[EDI Data Table] AS e
        LEFT JOIN dbo.tblCarts_Paint AS cp
            ON cp.[Cart ID] = e.cart_id
           AND cp.[Time Stamp] < @WindowEndExclusive
        LEFT JOIN StagedRepaintCarts AS rc ON rc.cart_id = e.cart_id
        WHERE e.cart_id IS NOT NULL
          AND e.Origin = N''F''
          AND cp.[Cart ID] IS NULL
          AND ISNULL(LTRIM(RTRIM(e.[Color])), N'''') <> N''''
          AND e.[Paint Block] NOT LIKE N''Arc%''
          AND (e.insp_line_end_disposition IS NULL OR e.insp_line_end_disposition = N''Repaint'')
          AND e.cart_load_verified_stamp >= DATEADD(day, -6, CONVERT(datetime2(0), @ReportDate))
          AND e.cart_load_verified_stamp < @WindowEndExclusive
    ), StagedCartGroups AS (
        SELECT
            block_id,
            cart_id,
            COUNT_BIG(*) AS piece_count,
            SUM(CASE WHEN part_class = N''Prd'' THEN 1 ELSE 0 END) AS production_piece_count,
            SUM(CASE WHEN part_class = N''BV'' THEN 1 ELSE 0 END) AS bv_piece_count,
            SUM(CASE WHEN part_class = N''Svc'' THEN 1 ELSE 0 END) AS service_piece_count,
            CASE
                WHEN MAX(CASE WHEN part_class = N''Svc'' THEN 1 ELSE 0 END) = 1 THEN N''Svc''
                WHEN MAX(CASE WHEN part_class = N''BV'' THEN 1 ELSE 0 END) = 1 THEN N''BV''
                ELSE N''Prd''
            END AS cart_class
        FROM StagedEligibleParts
        GROUP BY block_id, cart_id
        HAVING CONVERT(date, MIN(loaded_stamp)) >= DATEADD(day, -2, @ReportDate)
            OR (MAX(has_repaint) = 1 AND CONVERT(date, MIN(loaded_stamp)) >= DATEADD(day, -6, @ReportDate))
    ), StagedCurrent AS (
        SELECT
            @ReportDate AS report_date,
            COUNT_BIG(*) AS staged_carts,
            SUM(CASE WHEN cart_class = N''Prd'' THEN 1 ELSE 0 END) AS production_staged_carts,
            SUM(CASE WHEN cart_class = N''BV'' THEN 1 ELSE 0 END) AS bv_staged_carts,
            SUM(CASE WHEN cart_class = N''Svc'' THEN 1 ELSE 0 END) AS service_staged_carts,
            COALESCE(SUM(piece_count), 0) AS staged_pieces,
            COALESCE(SUM(production_piece_count), 0) AS production_staged_pieces,
            COALESCE(SUM(bv_piece_count), 0) AS bv_staged_pieces,
            COALESCE(SUM(service_piece_count), 0) AS service_staged_pieces
        FROM StagedCartGroups
    )
    SELECT
        d.report_date,
        COALESCE(l.parts_loaded, 0) AS parts_loaded,
        COALESCE(l.production_parts_loaded, 0) AS production_parts_loaded,
        COALESCE(l.bv_parts_loaded, 0) AS bv_parts_loaded,
        COALESCE(l.service_parts_loaded, 0) AS service_parts_loaded,
        COALESCE(l.n71_6164_parts_loaded, 0) AS n71_6164_parts_loaded,
        COALESCE(l.unique_pieces_loaded, 0) AS unique_pieces_loaded,
        COALESCE(l.carts_loaded, 0) AS carts_loaded,
        COALESCE(l.production_carts_loaded, 0) AS production_carts_loaded,
        COALESCE(l.bv_carts_loaded, 0) AS bv_carts_loaded,
        COALESCE(l.service_carts_loaded, 0) AS service_carts_loaded,
        COALESCE(l.n71_6164_carts_loaded, 0) AS n71_6164_carts_loaded,
        COALESCE(sc.staged_carts, 0) AS staged_carts,
        COALESCE(sc.production_staged_carts, 0) AS production_staged_carts,
        COALESCE(sc.bv_staged_carts, 0) AS bv_staged_carts,
        COALESCE(sc.service_staged_carts, 0) AS service_staged_carts,
        COALESCE(sc.staged_pieces, 0) AS staged_pieces,
        COALESCE(sc.production_staged_pieces, 0) AS production_staged_pieces,
        COALESCE(sc.bv_staged_pieces, 0) AS bv_staged_pieces,
        COALESCE(sc.service_staged_pieces, 0) AS service_staged_pieces,
        COALESCE(px.paint_processed, 0) AS paint_processed,
        COALESCE(px.production_paint_carts, 0) AS production_paint_carts,
        COALESCE(px.bv_paint_carts, 0) AS bv_paint_carts,
        COALESCE(px.service_paint_carts, 0) AS service_paint_carts,
        COALESCE(px.n71_6164_paint_carts, 0) AS n71_6164_paint_carts,
        COALESCE(px.paint_pieces_processed, 0) AS paint_pieces_processed,
        COALESCE(px.production_paint_pieces_processed, 0) AS production_paint_pieces_processed,
        COALESCE(px.bv_paint_pieces_processed, 0) AS bv_paint_pieces_processed,
        COALESCE(px.service_paint_pieces_processed, 0) AS service_paint_pieces_processed,
        COALESCE(px.n71_6164_paint_pieces_processed, 0) AS n71_6164_paint_pieces_processed,
        COALESCE(px.unique_pieces_processed, 0) AS unique_pieces_processed,
        COALESCE(p.paint_decision_pieces, 0) AS paint_decision_pieces,
        COALESCE(p.production_paint_decision_pieces, 0) AS production_paint_decision_pieces,
        COALESCE(p.bv_paint_decision_pieces, 0) AS bv_paint_decision_pieces,
        COALESCE(p.service_paint_decision_pieces, 0) AS service_paint_decision_pieces,
        COALESCE(p.ppy_approved, 0) AS ppy_approved,
        COALESCE(p.production_ppy_approved, 0) AS production_ppy_approved,
        COALESCE(p.bv_ppy_approved, 0) AS bv_ppy_approved,
        COALESCE(p.service_ppy_approved, 0) AS service_ppy_approved,
        COALESCE(p.ppy_repaint_count, 0) AS ppy_repaint_count,
        COALESCE(p.repaint_ppy_pending_count, 0) AS repaint_ppy_pending_count,
        COALESCE(p.paint_fty_total, 0) AS paint_fty_total,
        COALESCE(p.production_paint_fty_total, 0) AS production_paint_fty_total,
        COALESCE(p.bv_paint_fty_total, 0) AS bv_paint_fty_total,
        COALESCE(p.service_paint_fty_total, 0) AS service_paint_fty_total,
        COALESCE(p.paint_fty_approved, 0) AS paint_fty_approved,
        COALESCE(p.production_paint_fty_approved, 0) AS production_paint_fty_approved,
        COALESCE(p.bv_paint_fty_approved, 0) AS bv_paint_fty_approved,
        COALESCE(p.service_paint_fty_approved, 0) AS service_paint_fty_approved,
        COALESCE(p.paint_fty_repaint_count, 0) AS paint_fty_repaint_count,
        COALESCE(p.repaint_fty_pending_count, 0) AS repaint_fty_pending_count,
        COALESCE(p.fuka_paint_fty_repaint_count, 0) AS fuka_paint_fty_repaint_count,
        COALESCE(p.bumper_paint_fty_repaint_count, 0) AS bumper_paint_fty_repaint_count,
        COALESCE(p.fairing_paint_fty_repaint_count, 0) AS fairing_paint_fty_repaint_count,
        COALESCE(p.paint_fty_repair_count, 0) AS paint_fty_repair_count,
        COALESCE(p.fuka_paint_fty_repair_count, 0) AS fuka_paint_fty_repair_count,
        COALESCE(p.fairing_paint_fty_repair_count, 0) AS fairing_paint_fty_repair_count,
        COALESCE(p.bumper_paint_fty_repair_count, 0) AS bumper_paint_fty_repair_count,
        COALESCE(p.reject_ppy_total, 0) AS reject_ppy_total,
        COALESCE(p.reject_ppy_approved, 0) AS reject_ppy_approved,
        COALESCE(p.reject_ppy_rejected_count, 0) AS reject_ppy_rejected_count,
        COALESCE(p.reject_ppy_pending_count, 0) AS reject_ppy_pending_count,
        COALESCE(p.reject_fty_total, 0) AS reject_fty_total,
        COALESCE(p.reject_fty_approved, 0) AS reject_fty_approved,
        COALESCE(p.reject_fty_rejected_count, 0) AS reject_fty_rejected_count,
        COALESCE(p.reject_fty_pending_count, 0) AS reject_fty_pending_count,
        COALESCE(r.receiving_total, 0) AS receiving_total,
        COALESCE(r.receiving_approved, 0) AS receiving_approved,
        COALESCE(r.receiving_bumper_total, 0) AS receiving_bumper_total,
        COALESCE(r.receiving_bumper_approved, 0) AS receiving_bumper_approved,
        COALESCE(r.receiving_fairing_total, 0) AS receiving_fairing_total,
        COALESCE(r.receiving_fairing_approved, 0) AS receiving_fairing_approved,
        COALESCE(r.finesse_rejected_count, 0) AS finesse_rejected_count,
        COALESCE(r.finesse_repair_count, 0) AS finesse_repair_count,
        COALESCE(r.finesse_repaint_count, 0) AS finesse_repaint_count,
        COALESCE(r.finesse_pending_count, 0) AS finesse_pending_count,
        COALESCE(r.bumper_finesse_repair_count, 0) AS bumper_finesse_repair_count,
        COALESCE(r.fairing_finesse_repair_count, 0) AS fairing_finesse_repair_count,
        COALESCE(r.other_finesse_repair_count, 0) AS other_finesse_repair_count,
        COALESCE(rq.receiving_quantity, 0) AS receiving_quantity,
        COALESCE(f.final_total, 0) AS final_total,
        COALESCE(f.final_approved, 0) AS final_approved,
        COALESCE(f.final_fuka_total, 0) AS final_fuka_total,
        COALESCE(f.final_fuka_approved, 0) AS final_fuka_approved,
        COALESCE(f.final_bumper_total, 0) AS final_bumper_total,
        COALESCE(f.final_bumper_approved, 0) AS final_bumper_approved,
        COALESCE(f.final_fairing_total, 0) AS final_fairing_total,
        COALESCE(f.final_fairing_approved, 0) AS final_fairing_approved,
        COALESCE(fq.final_quantity, 0) AS final_quantity,
        COALESCE(e.eol_inspected, 0) AS eol_inspected,
        COALESCE(s.parts_shipped, 0) AS parts_shipped,
        COALESCE(s.painted_parts_shipped, 0) AS painted_parts_shipped,
        COALESCE(s.bumpers_shipped, 0) AS bumpers_shipped,
        COALESCE(a.parts_assembled, 0) AS parts_assembled,
        COALESCE(ca.complete_assy_sets, 0) AS complete_assy_sets,
        COALESCE(ca.mic_complete_assy_sets, 0) AS mic_complete_assy_sets,
        COALESCE(ca.painted_complete_assy_sets, 0) AS painted_complete_assy_sets,
        COALESCE(a.assembled_bumper_count, 0) AS assembled_bumper_count,
        COALESCE(a.mic_assembled_bumper_count, 0) AS mic_assembled_bumper_count,
        COALESCE(a.painted_assembled_bumper_count, 0) AS painted_assembled_bumper_count,
        COALESCE(ro.receiving_repair_qty, 0) AS receiving_repair_qty,
        COALESCE(ro.receiving_repaint_qty, 0) AS receiving_repaint_qty,
        COALESCE(td.trailers_prepared, 0) AS trailers_prepared,
        COALESCE(td.fuka_trailers_prepared, 0) AS fuka_trailers_prepared,
        COALESCE(td.bumper_trailers_prepared, 0) AS bumper_trailers_prepared,
        COALESCE(td.fairing_trailers_prepared, 0) AS fairing_trailers_prepared,
        COALESCE(td.other_trailers_prepared, 0) AS other_trailers_prepared,
        COALESCE(tsd.trailers_shipped, 0) AS trailers_shipped,
        COALESCE(rd.racks_shipped, 0) AS racks_shipped,
        COALESCE(rd.fuka_racks_shipped, 0) AS fuka_racks_shipped,
        COALESCE(rd.bumper_racks_shipped, 0) AS bumper_racks_shipped,
        COALESCE(rd.n71_6164_racks_shipped, 0) AS n71_6164_racks_shipped,
        COALESCE(rd.fairing_racks_shipped, 0) AS fairing_racks_shipped,
        COALESCE(rd.other_racks_shipped, 0) AS other_racks_shipped,
        s0.pieces_scheduled,
        s0.hours_scheduled,
        COALESCE(px.paint_hours, 0) AS paint_hours,
        CONVERT(decimal(10, 4), p.ppy_approved * 1.0 / NULLIF(p.paint_decision_pieces, 0)) AS ppy,
        CONVERT(decimal(10, 4), p.paint_fty_approved * 1.0 / NULLIF(p.paint_fty_total, 0)) AS paint_fty,
        CONVERT(decimal(10, 4), r.receiving_approved * 1.0 / NULLIF(r.receiving_total, 0)) AS receiving_fty,
        CONVERT(decimal(10, 4), f.final_approved * 1.0 / NULLIF(f.final_total, 0)) AS final_fty,
        CONVERT(decimal(10, 4), p.paint_fty_repaint_count * 1.0 / NULLIF(p.paint_fty_total, 0)) AS repaint_percentage,
        CONVERT(decimal(10, 4), p.reject_ppy_approved * 1.0 / NULLIF(p.reject_ppy_total, 0)) AS reject_ppy,
        CONVERT(decimal(10, 4), p.reject_fty_approved * 1.0 / NULLIF(p.reject_fty_total, 0)) AS reject_fty,
        CONVERT(decimal(10, 4),
            CASE WHEN COALESCE(px.paint_pieces_processed, 0) = 0 THEN NULL ELSE
                CASE WHEN
                    (px.paint_pieces_processed * 1.0 / NULLIF(s0.pieces_scheduled, 0)) *
                    ((p.paint_fty_total - p.paint_fty_repaint_count) * 1.0 / NULLIF(p.paint_fty_total, 0)) *
                    CASE WHEN px.paint_hours * 1.0 / NULLIF(s0.hours_scheduled, 0) > 1 THEN 1.0 ELSE px.paint_hours * 1.0 / NULLIF(s0.hours_scheduled, 0) END > 1 THEN 1.0 ELSE
                    (px.paint_pieces_processed * 1.0 / NULLIF(s0.pieces_scheduled, 0)) *
                    ((p.paint_fty_total - p.paint_fty_repaint_count) * 1.0 / NULLIF(p.paint_fty_total, 0)) *
                    CASE WHEN px.paint_hours * 1.0 / NULLIF(s0.hours_scheduled, 0) > 1 THEN 1.0 ELSE px.paint_hours * 1.0 / NULLIF(s0.hours_scheduled, 0) END
                END
            END
        ) AS paint_oee,
        CASE
            WHEN COALESCE(px.paint_pieces_processed, 0) = 0 THEN N''No Data''
            WHEN s0.pieces_scheduled IS NULL OR s0.hours_scheduled IS NULL
              OR s0.pieces_scheduled <= 0 OR s0.hours_scheduled <= 0 THEN N''Missing Schedule''
            WHEN
                (px.paint_pieces_processed * 1.0 / NULLIF(s0.pieces_scheduled, 0)) *
                ((p.paint_fty_total - p.paint_fty_repaint_count) * 1.0 / NULLIF(p.paint_fty_total, 0)) *
                CASE WHEN px.paint_hours * 1.0 / NULLIF(s0.hours_scheduled, 0) > 1 THEN 1.0 ELSE px.paint_hours * 1.0 / NULLIF(s0.hours_scheduled, 0) END > 1
                OR px.paint_hours > s0.hours_scheduled THEN N''Calculated (capped)''
            ELSE N''Calculated''
        END AS oee_status
    INTO #DailyMetrics
    FROM DateRange AS d
    LEFT JOIN LoadedDaily AS l ON l.report_date = d.report_date
    LEFT JOIN PaintExitDaily AS px ON px.report_date = d.report_date
    LEFT JOIN PaintDaily AS p ON p.report_date = d.report_date
    LEFT JOIN #ReceivingFirst AS r ON r.event_date = d.report_date
    LEFT JOIN ReceivingQuantityDaily AS rq ON rq.report_date = d.report_date
    LEFT JOIN #FinalFirst AS f ON f.event_date = d.report_date
    LEFT JOIN FinalQuantityDaily AS fq ON fq.report_date = d.report_date
    LEFT JOIN EolDaily AS e ON e.report_date = d.report_date
    LEFT JOIN ShipDaily AS s ON s.report_date = d.report_date
    LEFT JOIN AssemblyDaily AS a ON a.report_date = d.report_date
    LEFT JOIN CompleteAssemblyDaily AS ca ON ca.report_date = d.report_date
    LEFT JOIN ReceivingOutcomeDaily AS ro ON ro.report_date = d.report_date
    LEFT JOIN TrailerDaily AS td ON td.report_date = d.report_date
    LEFT JOIN StagedCurrent AS sc ON sc.report_date = d.report_date
    LEFT JOIN TrailerDepartureDaily AS tsd ON tsd.report_date = d.report_date
    LEFT JOIN RackDaily AS rd ON rd.report_date = d.report_date
    LEFT JOIN ScheduleDaily AS s0 ON s0.report_date = d.report_date
    OPTION (MAXRECURSION 1000);

    CREATE TABLE #Periods (
        period_order int NOT NULL,
        period_label nvarchar(80) NOT NULL,
        period_type nvarchar(20) NOT NULL,
        period_start date NOT NULL,
        period_end_exclusive date NOT NULL
    );

    INSERT INTO #Periods VALUES
        (1, CONCAT(N''All of '', YEAR(@ReportDate) - 1), N''YEAR'', DATEFROMPARTS(YEAR(@ReportDate) - 1, 1, 1), @CurrentYearStart);

    ;WITH QuarterRange AS (
        SELECT @CurrentYearStart AS period_start
        UNION ALL
        SELECT DATEADD(month, 3, period_start)
        FROM QuarterRange
        WHERE DATEADD(month, 3, period_start) <= @QuarterStart
    )
    INSERT INTO #Periods
    SELECT
        10 + ROW_NUMBER() OVER (ORDER BY period_start),
        CONCAT(N''Q'', DATEPART(quarter, period_start), N'' '', YEAR(period_start), CASE WHEN period_start = @QuarterStart THEN N'' (partial)'' ELSE N'''' END),
        N''QUARTER'',
        period_start,
        DATEADD(month, 3, period_start)
    FROM QuarterRange
    OPTION (MAXRECURSION 8);

    ;WITH MonthRange AS (
        SELECT @QuarterStart AS period_start
        UNION ALL
        SELECT DATEADD(month, 1, period_start)
        FROM MonthRange
        WHERE DATEADD(month, 1, period_start) <= @MonthStart
    )
    INSERT INTO #Periods
    SELECT
        20 + ROW_NUMBER() OVER (ORDER BY period_start),
        CONCAT(DATENAME(month, period_start), N'' '', YEAR(period_start), CASE WHEN period_start = @MonthStart THEN N'' (partial)'' ELSE N'''' END),
        N''MONTH'',
        period_start,
        DATEADD(month, 1, period_start)
    FROM MonthRange
    OPTION (MAXRECURSION 12);

    ;WITH LongMonthRange AS (
        SELECT DATEADD(month, -10, @MonthStart) AS period_start
        UNION ALL
        SELECT DATEADD(month, 1, period_start)
        FROM LongMonthRange
        WHERE DATEADD(month, 1, period_start) <= @MonthStart
    )
    INSERT INTO #Periods
    SELECT
        200 + ROW_NUMBER() OVER (ORDER BY period_start),
        CONCAT(DATENAME(month, period_start), N'' '', YEAR(period_start), CASE WHEN period_start = @MonthStart THEN N'' (partial)'' ELSE N'''' END),
        N''LONG_MONTH'',
        period_start,
        DATEADD(month, 1, period_start)
    FROM LongMonthRange
    OPTION (MAXRECURSION 24);

    IF @MonthStart <= @ReportDate AND @FirstSundayAfterMonthStart > @MonthStart
    BEGIN
        INSERT INTO #Periods
        VALUES (
            30,
            CONCAT(CONVERT(varchar(10), @MonthStart, 101), N''-'', CONVERT(varchar(10), DATEADD(day, -1, @FirstSundayAfterMonthStart), 101)),
            N''WEEK'',
            @MonthStart,
            CASE WHEN @FirstSundayAfterMonthStart > DATEADD(day, 1, @ReportDate) THEN DATEADD(day, 1, @ReportDate) ELSE @FirstSundayAfterMonthStart END
        );
    END;

    ;WITH WeekRange AS (
        SELECT @FirstSundayAfterMonthStart AS period_start
        WHERE @FirstSundayAfterMonthStart <= @WeekStart
        UNION ALL
        SELECT DATEADD(day, 7, period_start)
        FROM WeekRange
        WHERE DATEADD(day, 7, period_start) <= @WeekStart
    )
    INSERT INTO #Periods
    SELECT
        30 + ROW_NUMBER() OVER (ORDER BY period_start),
        CONCAT(CONVERT(varchar(10), period_start, 101), N''-'', CONVERT(varchar(10), CASE WHEN DATEADD(day, 7, period_start) > DATEADD(day, 1, @ReportDate) THEN @ReportDate ELSE DATEADD(day, 6, period_start) END, 101), CASE WHEN period_start = @WeekStart THEN N'' (partial)'' ELSE N'''' END),
        N''WEEK'',
        period_start,
        CASE WHEN DATEADD(day, 7, period_start) > DATEADD(day, 1, @ReportDate) THEN DATEADD(day, 1, @ReportDate) ELSE DATEADD(day, 7, period_start) END
    FROM WeekRange
    OPTION (MAXRECURSION 52);

    ;WITH DayRange AS (
        SELECT @WeekStart AS period_start
        WHERE @WeekStart <= @ReportDate
        UNION ALL
        SELECT DATEADD(day, 1, period_start)
        FROM DayRange
        WHERE period_start < @ReportDate
    )
    INSERT INTO #Periods
    SELECT
        100 + ROW_NUMBER() OVER (ORDER BY period_start),
        CONVERT(varchar(10), period_start, 101),
        N''DAY'',
        period_start,
        DATEADD(day, 1, period_start)
    FROM DayRange
    OPTION (MAXRECURSION 14);

    SELECT
        @HistoryStart AS history_start,
        @ReportDate AS report_date,
        @WeekStart AS current_week_start,
        @MonthStart AS current_month_start,
        @QuarterStart AS current_quarter_start;

    SELECT
        p.period_order,
        p.period_label,
        p.period_type,
        p.period_start,
        DATEADD(day, -1, p.period_end_exclusive) AS period_end,
        CASE WHEN SUM(CASE WHEN d.parts_loaded > 0 OR d.paint_processed > 0 OR d.eol_inspected > 0 OR d.receiving_total > 0 OR d.receiving_quantity > 0 OR d.final_total > 0 OR d.final_quantity > 0 OR d.parts_shipped > 0 OR d.parts_assembled > 0 THEN 1 ELSE 0 END) > 0 THEN 1 ELSE 0 END AS data_available,
        COUNT(d.report_date) AS calendar_days,
        COUNT(CASE WHEN d.parts_loaded > 0 OR d.paint_processed > 0 OR d.eol_inspected > 0 OR d.receiving_total > 0 OR d.receiving_quantity > 0 OR d.final_total > 0 OR d.final_quantity > 0 OR d.parts_shipped > 0 OR d.parts_assembled > 0 THEN 1 END) AS data_days,
        COALESCE(SUM(d.parts_loaded), 0) AS parts_loaded,
        COALESCE(SUM(d.production_parts_loaded), 0) AS production_parts_loaded,
        COALESCE(SUM(d.bv_parts_loaded), 0) AS bv_parts_loaded,
        COALESCE(SUM(d.service_parts_loaded), 0) AS service_parts_loaded,
        COALESCE(SUM(d.n71_6164_parts_loaded), 0) AS n71_6164_parts_loaded,
        COALESCE(SUM(d.unique_pieces_loaded), 0) AS unique_pieces_loaded,
        COALESCE(SUM(d.carts_loaded), 0) AS carts_loaded,
        COALESCE(SUM(d.production_carts_loaded), 0) AS production_carts_loaded,
        COALESCE(SUM(d.bv_carts_loaded), 0) AS bv_carts_loaded,
        COALESCE(SUM(d.service_carts_loaded), 0) AS service_carts_loaded,
        COALESCE(SUM(d.n71_6164_carts_loaded), 0) AS n71_6164_carts_loaded,
        COALESCE(SUM(d.staged_carts), 0) AS staged_carts,
        COALESCE(SUM(d.production_staged_carts), 0) AS production_staged_carts,
        COALESCE(SUM(d.bv_staged_carts), 0) AS bv_staged_carts,
        COALESCE(SUM(d.service_staged_carts), 0) AS service_staged_carts,
        COALESCE(SUM(d.staged_pieces), 0) AS staged_pieces,
        COALESCE(SUM(d.production_staged_pieces), 0) AS production_staged_pieces,
        COALESCE(SUM(d.bv_staged_pieces), 0) AS bv_staged_pieces,
        COALESCE(SUM(d.service_staged_pieces), 0) AS service_staged_pieces,
        COALESCE(SUM(d.paint_processed), 0) AS paint_processed,
        COALESCE(SUM(d.production_paint_carts), 0) AS production_paint_carts,
        COALESCE(SUM(d.bv_paint_carts), 0) AS bv_paint_carts,
        COALESCE(SUM(d.service_paint_carts), 0) AS service_paint_carts,
        COALESCE(SUM(d.n71_6164_paint_carts), 0) AS n71_6164_paint_carts,
        COALESCE(SUM(d.paint_pieces_processed), 0) AS paint_pieces_processed,
        COALESCE(SUM(d.production_paint_pieces_processed), 0) AS production_paint_pieces_processed,
        COALESCE(SUM(d.bv_paint_pieces_processed), 0) AS bv_paint_pieces_processed,
        COALESCE(SUM(d.service_paint_pieces_processed), 0) AS service_paint_pieces_processed,
        COALESCE(SUM(d.n71_6164_paint_pieces_processed), 0) AS n71_6164_paint_pieces_processed,
        COALESCE(SUM(d.unique_pieces_processed), 0) AS unique_pieces_processed,
        COALESCE(SUM(d.paint_decision_pieces), 0) AS paint_decision_pieces,
        COALESCE(SUM(d.production_paint_decision_pieces), 0) AS production_paint_decision_pieces,
        COALESCE(SUM(d.bv_paint_decision_pieces), 0) AS bv_paint_decision_pieces,
        COALESCE(SUM(d.service_paint_decision_pieces), 0) AS service_paint_decision_pieces,
        COALESCE(SUM(d.ppy_approved), 0) AS ppy_approved,
        COALESCE(SUM(d.production_ppy_approved), 0) AS production_ppy_approved,
        COALESCE(SUM(d.bv_ppy_approved), 0) AS bv_ppy_approved,
        COALESCE(SUM(d.service_ppy_approved), 0) AS service_ppy_approved,
        COALESCE(SUM(d.ppy_repaint_count), 0) AS ppy_repaint_count,
        COALESCE(SUM(d.repaint_ppy_pending_count), 0) AS repaint_ppy_pending_count,
        COALESCE(SUM(d.paint_fty_total), 0) AS paint_fty_total,
        COALESCE(SUM(d.production_paint_fty_total), 0) AS production_paint_fty_total,
        COALESCE(SUM(d.bv_paint_fty_total), 0) AS bv_paint_fty_total,
        COALESCE(SUM(d.service_paint_fty_total), 0) AS service_paint_fty_total,
        COALESCE(SUM(d.paint_fty_approved), 0) AS paint_fty_approved,
        COALESCE(SUM(d.production_paint_fty_approved), 0) AS production_paint_fty_approved,
        COALESCE(SUM(d.bv_paint_fty_approved), 0) AS bv_paint_fty_approved,
        COALESCE(SUM(d.service_paint_fty_approved), 0) AS service_paint_fty_approved,
        COALESCE(SUM(d.paint_fty_repaint_count), 0) AS paint_fty_repaint_count,
        COALESCE(SUM(d.repaint_fty_pending_count), 0) AS repaint_fty_pending_count,
        COALESCE(SUM(d.fuka_paint_fty_repaint_count), 0) AS fuka_paint_fty_repaint_count,
        COALESCE(SUM(d.bumper_paint_fty_repaint_count), 0) AS bumper_paint_fty_repaint_count,
        COALESCE(SUM(d.fairing_paint_fty_repaint_count), 0) AS fairing_paint_fty_repaint_count,
        COALESCE(SUM(d.paint_fty_repair_count), 0) AS paint_fty_repair_count,
        COALESCE(SUM(d.fuka_paint_fty_repair_count), 0) AS fuka_paint_fty_repair_count,
        COALESCE(SUM(d.fairing_paint_fty_repair_count), 0) AS fairing_paint_fty_repair_count,
        COALESCE(SUM(d.bumper_paint_fty_repair_count), 0) AS bumper_paint_fty_repair_count,
        COALESCE(SUM(d.reject_ppy_total), 0) AS reject_ppy_total,
        COALESCE(SUM(d.reject_ppy_approved), 0) AS reject_ppy_approved,
        COALESCE(SUM(d.reject_ppy_rejected_count), 0) AS reject_ppy_rejected_count,
        COALESCE(SUM(d.reject_ppy_pending_count), 0) AS reject_ppy_pending_count,
        COALESCE(SUM(d.reject_fty_total), 0) AS reject_fty_total,
        COALESCE(SUM(d.reject_fty_approved), 0) AS reject_fty_approved,
        COALESCE(SUM(d.reject_fty_rejected_count), 0) AS reject_fty_rejected_count,
        COALESCE(SUM(d.reject_fty_pending_count), 0) AS reject_fty_pending_count,
        COALESCE(SUM(d.receiving_total), 0) AS receiving_total,
        COALESCE(SUM(d.receiving_approved), 0) AS receiving_approved,
        COALESCE(SUM(d.receiving_bumper_total), 0) AS receiving_bumper_total,
        COALESCE(SUM(d.receiving_bumper_approved), 0) AS receiving_bumper_approved,
        COALESCE(SUM(d.receiving_fairing_total), 0) AS receiving_fairing_total,
        COALESCE(SUM(d.receiving_fairing_approved), 0) AS receiving_fairing_approved,
        COALESCE(SUM(d.finesse_rejected_count), 0) AS finesse_rejected_count,
        COALESCE(SUM(d.finesse_repair_count), 0) AS finesse_repair_count,
        COALESCE(SUM(d.finesse_repaint_count), 0) AS finesse_repaint_count,
        COALESCE(SUM(d.finesse_pending_count), 0) AS finesse_pending_count,
        COALESCE(SUM(d.bumper_finesse_repair_count), 0) AS bumper_finesse_repair_count,
        COALESCE(SUM(d.fairing_finesse_repair_count), 0) AS fairing_finesse_repair_count,
        COALESCE(SUM(d.other_finesse_repair_count), 0) AS other_finesse_repair_count,
        COALESCE(SUM(d.receiving_quantity), 0) AS receiving_quantity,
        COALESCE(SUM(d.final_total), 0) AS final_total,
        COALESCE(SUM(d.final_approved), 0) AS final_approved,
        COALESCE(SUM(d.final_fuka_total), 0) AS final_fuka_total,
        COALESCE(SUM(d.final_fuka_approved), 0) AS final_fuka_approved,
        COALESCE(SUM(d.final_bumper_total), 0) AS final_bumper_total,
        COALESCE(SUM(d.final_bumper_approved), 0) AS final_bumper_approved,
        COALESCE(SUM(d.final_fairing_total), 0) AS final_fairing_total,
        COALESCE(SUM(d.final_fairing_approved), 0) AS final_fairing_approved,
        COALESCE(SUM(d.final_quantity), 0) AS final_quantity,
        COALESCE(SUM(d.eol_inspected), 0) AS eol_inspected,
        COALESCE(SUM(d.parts_shipped), 0) AS parts_shipped,
        COALESCE(SUM(d.painted_parts_shipped), 0) AS painted_parts_shipped,
        COALESCE(SUM(d.bumpers_shipped), 0) AS bumpers_shipped,
        COALESCE(SUM(d.parts_assembled), 0) AS parts_assembled,
        COALESCE(SUM(d.complete_assy_sets), 0) AS complete_assy_sets,
        COALESCE(SUM(d.mic_complete_assy_sets), 0) AS mic_complete_assy_sets,
        COALESCE(SUM(d.painted_complete_assy_sets), 0) AS painted_complete_assy_sets,
        COALESCE(SUM(d.assembled_bumper_count), 0) AS assembled_bumper_count,
        COALESCE(SUM(d.mic_assembled_bumper_count), 0) AS mic_assembled_bumper_count,
        COALESCE(SUM(d.painted_assembled_bumper_count), 0) AS painted_assembled_bumper_count,
        COALESCE(SUM(d.receiving_repair_qty), 0) AS receiving_repair_qty,
        COALESCE(SUM(d.receiving_repaint_qty), 0) AS receiving_repaint_qty,
        COALESCE(SUM(d.trailers_prepared), 0) AS trailers_prepared,
        COALESCE(SUM(d.fuka_trailers_prepared), 0) AS fuka_trailers_prepared,
        COALESCE(SUM(d.bumper_trailers_prepared), 0) AS bumper_trailers_prepared,
        COALESCE(SUM(d.fairing_trailers_prepared), 0) AS fairing_trailers_prepared,
        COALESCE(SUM(d.other_trailers_prepared), 0) AS other_trailers_prepared,
        COALESCE(SUM(d.trailers_shipped), 0) AS trailers_shipped,
        COALESCE(SUM(d.racks_shipped), 0) AS racks_shipped,
        COALESCE(SUM(d.fuka_racks_shipped), 0) AS fuka_racks_shipped,
        COALESCE(SUM(d.bumper_racks_shipped), 0) AS bumper_racks_shipped,
        COALESCE(SUM(d.n71_6164_racks_shipped), 0) AS n71_6164_racks_shipped,
        COALESCE(SUM(d.fairing_racks_shipped), 0) AS fairing_racks_shipped,
        COALESCE(SUM(d.other_racks_shipped), 0) AS other_racks_shipped,
        COALESCE(SUM(d.pieces_scheduled), 0) AS pieces_scheduled,
        COALESCE(SUM(d.hours_scheduled), 0) AS hours_scheduled,
        COALESCE(SUM(d.paint_hours), 0) AS paint_hours,
        CONVERT(decimal(10, 4), COALESCE(SUM(d.ppy_approved), 0) * 1.0 / NULLIF(COALESCE(SUM(d.paint_decision_pieces), 0), 0)) AS ppy,
        CONVERT(decimal(10, 4), COALESCE(SUM(d.paint_fty_approved), 0) * 1.0 / NULLIF(COALESCE(SUM(d.paint_fty_total), 0), 0)) AS paint_fty,
        CONVERT(decimal(10, 4), COALESCE(SUM(d.receiving_approved), 0) * 1.0 / NULLIF(COALESCE(SUM(d.receiving_total), 0), 0)) AS receiving_fty,
        CONVERT(decimal(10, 4), COALESCE(SUM(d.final_approved), 0) * 1.0 / NULLIF(COALESCE(SUM(d.final_total), 0), 0)) AS final_fty,
        CONVERT(decimal(10, 4), COALESCE(SUM(d.paint_fty_repaint_count), 0) * 1.0 / NULLIF(COALESCE(SUM(d.paint_fty_total), 0), 0)) AS repaint_percentage,
        CONVERT(decimal(10, 4), COALESCE(SUM(d.reject_ppy_approved), 0) * 1.0 / NULLIF(COALESCE(SUM(d.reject_ppy_total), 0), 0)) AS reject_ppy,
        CONVERT(decimal(10, 4), COALESCE(SUM(d.reject_fty_approved), 0) * 1.0 / NULLIF(COALESCE(SUM(d.reject_fty_total), 0), 0)) AS reject_fty,
        CONVERT(decimal(10, 4),
            CASE
                WHEN SUM(d.paint_pieces_processed) = 0 THEN NULL
                WHEN SUM(CASE WHEN d.paint_pieces_processed > 0 AND (d.pieces_scheduled IS NULL OR d.hours_scheduled IS NULL OR d.pieces_scheduled <= 0 OR d.hours_scheduled <= 0) THEN 1 ELSE 0 END) > 0 THEN NULL
                ELSE
                    CASE WHEN
                        (COALESCE(SUM(d.paint_pieces_processed), 0) * 1.0 / NULLIF(COALESCE(SUM(d.pieces_scheduled), 0), 0)) *
                        ((COALESCE(SUM(d.paint_fty_total), 0) - COALESCE(SUM(d.paint_fty_repaint_count), 0)) * 1.0 / NULLIF(COALESCE(SUM(d.paint_fty_total), 0), 0)) *
                        CASE WHEN COALESCE(SUM(d.paint_hours), 0) * 1.0 / NULLIF(COALESCE(SUM(d.hours_scheduled), 0), 0) > 1 THEN 1.0 ELSE COALESCE(SUM(d.paint_hours), 0) * 1.0 / NULLIF(COALESCE(SUM(d.hours_scheduled), 0), 0) END > 1 THEN 1.0 ELSE
                        (COALESCE(SUM(d.paint_pieces_processed), 0) * 1.0 / NULLIF(COALESCE(SUM(d.pieces_scheduled), 0), 0)) *
                        ((COALESCE(SUM(d.paint_fty_total), 0) - COALESCE(SUM(d.paint_fty_repaint_count), 0)) * 1.0 / NULLIF(COALESCE(SUM(d.paint_fty_total), 0), 0)) *
                        CASE WHEN COALESCE(SUM(d.paint_hours), 0) * 1.0 / NULLIF(COALESCE(SUM(d.hours_scheduled), 0), 0) > 1 THEN 1.0 ELSE COALESCE(SUM(d.paint_hours), 0) * 1.0 / NULLIF(COALESCE(SUM(d.hours_scheduled), 0), 0) END
                    END
            END
        ) AS paint_oee,
        CASE
            WHEN SUM(d.paint_pieces_processed) = 0 THEN N''No Data''
            WHEN SUM(CASE WHEN d.paint_pieces_processed > 0 AND (d.pieces_scheduled IS NULL OR d.hours_scheduled IS NULL OR d.pieces_scheduled <= 0 OR d.hours_scheduled <= 0) THEN 1 ELSE 0 END) > 0 THEN N''Missing Schedule''
            WHEN
                (COALESCE(SUM(d.paint_pieces_processed), 0) * 1.0 / NULLIF(COALESCE(SUM(d.pieces_scheduled), 0), 0)) *
                ((COALESCE(SUM(d.paint_fty_total), 0) - COALESCE(SUM(d.paint_fty_repaint_count), 0)) * 1.0 / NULLIF(COALESCE(SUM(d.paint_fty_total), 0), 0)) *
                CASE WHEN COALESCE(SUM(d.paint_hours), 0) * 1.0 / NULLIF(COALESCE(SUM(d.hours_scheduled), 0), 0) > 1 THEN 1.0 ELSE COALESCE(SUM(d.paint_hours), 0) * 1.0 / NULLIF(COALESCE(SUM(d.hours_scheduled), 0), 0) END > 1
                OR COALESCE(SUM(d.paint_hours), 0) > COALESCE(SUM(d.hours_scheduled), 0) THEN N''Calculated (capped)''
            ELSE N''Calculated''
        END AS oee_status
    INTO #PeriodMetrics
    FROM #Periods AS p
    LEFT JOIN #DailyMetrics AS d
        ON d.report_date >= p.period_start
       AND d.report_date < p.period_end_exclusive
    GROUP BY p.period_order, p.period_label, p.period_type, p.period_start, p.period_end_exclusive;

    SELECT * FROM #PeriodMetrics WHERE data_available = 1 ORDER BY period_order;
    SELECT * FROM #PeriodMetrics WHERE period_type = N''DAY'' ORDER BY period_order;
    SELECT * FROM #PeriodMetrics WHERE period_type = N''WEEK'' AND data_available = 1 ORDER BY period_order;
    SELECT * FROM #PeriodMetrics WHERE period_type = N''MONTH'' AND data_available = 1 ORDER BY period_order;
    SELECT * FROM #PeriodMetrics WHERE period_type = N''QUARTER'' AND data_available = 1 ORDER BY period_order;
    SELECT * FROM #PeriodMetrics WHERE period_type = N''YEAR'' AND data_available = 1 ORDER BY period_order;
    SELECT * FROM #PeriodMetrics WHERE period_type = N''LONG_MONTH'' AND data_available = 1 ORDER BY period_order;

    /* RESTRICTED_DRILLDOWN_LEGACY_PAINTER_GATE_BEGIN */
    IF @IncludeRestrictedDetail = 1
    BEGIN
        /* Painter performance at daily grain. Minutes are elapsed booth-session
           minutes overlapping each calendar day, not inferred spray time. */
        ;WITH PainterParts AS (
            SELECT
                CONVERT(date, ci.PaintDate_In) AS report_date,
                COALESCE(NULLIF(LTRIM(RTRIM(pe.PainterName)), N''''), NULLIF(LTRIM(RTRIM(ci.Painter_Name)), N''''), N''Unknown'') AS painter_name,
                s.BoothNumber AS booth_number,
                COUNT(DISTINCT ci.Cart_ID_In) AS carts_painted,
                COUNT(DISTINCT h.part_id) AS parts_painted
            FROM dbo.tblCarts_Paint_Oven_In AS ci
            LEFT JOIN dbo.tblPaintBoothSessions AS s ON s.PaintBoothSessionID = ci.PaintBoothSessionID
            LEFT JOIN dbo.tblPaintBoothEmployees AS pe ON pe.EmployeeID = s.EmployeeID
            LEFT JOIN #History AS h
                ON h.PaintCart_ID = ci.Cart_ID_In
               AND h.moment_category = N''paint_oven_exited''
               AND h.moment_date = CONVERT(date, ci.PaintDate_In)
            WHERE ci.PaintDate_In >= @HistoryStart
              AND ci.PaintDate_In < DATEADD(day, 1, @ReportDate)
            GROUP BY CONVERT(date, ci.PaintDate_In), COALESCE(NULLIF(LTRIM(RTRIM(pe.PainterName)), N''''), NULLIF(LTRIM(RTRIM(ci.Painter_Name)), N''''), N''Unknown''), s.BoothNumber
        ), PainterTime AS (
            SELECT
                d.report_date,
                COALESCE(NULLIF(LTRIM(RTRIM(pe.PainterName)), N''''), NULLIF(LTRIM(RTRIM(ps.PainterNameAtLogin)), N''''), N''Unknown'') AS painter_name,
                ps.BoothNumber AS booth_number,
                SUM(CASE WHEN x.session_end > x.session_start THEN DATEDIFF(minute, x.session_start, x.session_end) ELSE 0 END) AS minutes_logged
            FROM #DailyMetrics AS d
            INNER JOIN dbo.tblPaintBoothSessions AS ps
                ON ps.SignedInAt < DATEADD(day, 1, CONVERT(datetime2, d.report_date))
               AND (ps.SignedOutAt IS NULL OR ps.SignedOutAt > CONVERT(datetime2, d.report_date))
            LEFT JOIN dbo.tblPaintBoothEmployees AS pe ON pe.EmployeeID = ps.EmployeeID
            CROSS APPLY (SELECT
                CASE WHEN ps.SignedInAt < CONVERT(datetime2, d.report_date) THEN CONVERT(datetime2, d.report_date) ELSE ps.SignedInAt END AS session_start,
                CASE WHEN ps.SignedOutAt IS NULL OR ps.SignedOutAt > DATEADD(day, 1, CONVERT(datetime2, d.report_date)) THEN DATEADD(day, 1, CONVERT(datetime2, d.report_date)) ELSE ps.SignedOutAt END AS session_end
            ) AS x
            GROUP BY d.report_date, COALESCE(NULLIF(LTRIM(RTRIM(pe.PainterName)), N''''), NULLIF(LTRIM(RTRIM(ps.PainterNameAtLogin)), N''''), N''Unknown''), ps.BoothNumber
        )
        SELECT
            COALESCE(p.report_date, t.report_date) AS report_date,
            COALESCE(p.painter_name, t.painter_name) AS painter_name,
            COALESCE(p.booth_number, t.booth_number) AS booth_number,
            COALESCE(p.carts_painted, 0) AS carts_painted,
            COALESCE(p.parts_painted, 0) AS parts_painted,
            COALESCE(t.minutes_logged, 0) AS minutes_logged,
            CONVERT(decimal(10, 2), COALESCE(p.parts_painted, 0) * 60.0 / NULLIF(t.minutes_logged, 0)) AS parts_per_hour
        FROM PainterParts AS p
        FULL OUTER JOIN PainterTime AS t
            ON t.report_date = p.report_date
           AND t.painter_name = p.painter_name
           AND (t.booth_number = p.booth_number OR (t.booth_number IS NULL AND p.booth_number IS NULL))
        WHERE COALESCE(p.report_date, t.report_date) >= @WeekStart
          AND COALESCE(p.report_date, t.report_date) <= @ReportDate
        ORDER BY report_date, painter_name, booth_number;
    END
    ELSE
    BEGIN
        /* Preserve result-set index 8 without returning employee data. */
        SELECT
            CONVERT(date, NULL) AS report_date,
            CONVERT(nvarchar(200), NULL) AS painter_name,
            CONVERT(tinyint, NULL) AS booth_number,
            CONVERT(int, NULL) AS carts_painted,
            CONVERT(int, NULL) AS parts_painted,
            CONVERT(int, NULL) AS minutes_logged,
            CONVERT(decimal(10, 2), NULL) AS parts_per_hour
        WHERE 1 = 0;
    END;
    /* RESTRICTED_DRILLDOWN_LEGACY_PAINTER_GATE_END */

    /* Top three defect descriptions by inspection step. */
    ;WITH DefectCounts AS (
        SELECT
            CASE
                WHEN h.moment_category = N''receiving_reject'' THEN N''Receiving''
                WHEN h.moment_category IN (N''end_of_line_repair'', N''end_of_line_repaint'', N''end_of_line_direct_repaint'', N''end_of_line_reject'') THEN N''End of Line''
                WHEN h.moment_category = N''final_reject'' THEN N''Final''
            END AS inspection_step,
            COALESCE(NULLIF(LTRIM(RTRIM(d.Defect)), N''''), NULLIF(LTRIM(RTRIM(dt.[Defect Type])), N''''), NULLIF(LTRIM(RTRIM(h.defect_code)), N''''), N''Unspecified'') AS defect_description,
            COUNT(*) AS defect_count
        FROM #History AS h
        LEFT JOIN dbo.Defects AS d ON TRY_CONVERT(int, h.defect_code) = d.ID
        LEFT JOIN dbo.[Defect Type] AS dt ON CONVERT(nvarchar(100), dt.[Defect Code]) = h.defect_code
        WHERE h.moment_date = @ReportDate
          AND h.moment_category IN (N''receiving_reject'', N''end_of_line_repair'', N''end_of_line_repaint'', N''end_of_line_direct_repaint'', N''end_of_line_reject'', N''final_reject'')
        GROUP BY
            CASE
                WHEN h.moment_category = N''receiving_reject'' THEN N''Receiving''
                WHEN h.moment_category IN (N''end_of_line_repair'', N''end_of_line_repaint'', N''end_of_line_direct_repaint'', N''end_of_line_reject'') THEN N''End of Line''
                WHEN h.moment_category = N''final_reject'' THEN N''Final''
            END,
            COALESCE(NULLIF(LTRIM(RTRIM(d.Defect)), N''''), NULLIF(LTRIM(RTRIM(dt.[Defect Type])), N''''), NULLIF(LTRIM(RTRIM(h.defect_code)), N''''), N''Unspecified'')
    ), RankedDefects AS (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY inspection_step ORDER BY defect_count DESC, defect_description) AS defect_rank
        FROM DefectCounts
    )
    SELECT inspection_step, defect_description, defect_count, defect_rank
    FROM RankedDefects
    WHERE defect_rank <= 3
    ORDER BY inspection_step, defect_rank;

    /* Rejection detail with the same inspection-step and description mapping. */
    SELECT
        CASE
            WHEN h.moment_category = N''receiving_reject'' THEN N''Receiving''
            WHEN h.moment_category IN (N''end_of_line_repair'', N''end_of_line_repaint'', N''end_of_line_direct_repaint'', N''end_of_line_reject'') THEN N''End of Line''
            WHEN h.moment_category = N''final_reject'' THEN N''Final''
        END AS inspection_step,
        h.moment_category AS rejection_event,
        h.moment_date,
        CONVERT(varchar(12), h.moment_time, 114) AS moment_time,
        h.part_id,
        e.[Part Number] AS part_number,
        e.Sequence,
        e.Color,
        COALESCE(NULLIF(LTRIM(RTRIM(d.Defect)), N''''), NULLIF(LTRIM(RTRIM(dt.[Defect Type])), N''''), NULLIF(LTRIM(RTRIM(h.defect_code)), N''''), N''Unspecified'') AS defect_description,
        h.moment_text,
        h.user_name
    FROM #History AS h
    LEFT JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = h.part_id
    LEFT JOIN dbo.Defects AS d ON TRY_CONVERT(int, h.defect_code) = d.ID
    LEFT JOIN dbo.[Defect Type] AS dt ON CONVERT(nvarchar(100), dt.[Defect Code]) = h.defect_code
    WHERE h.moment_date = @ReportDate
      AND h.moment_category IN (N''receiving_reject'', N''end_of_line_repair'', N''end_of_line_repaint'', N''end_of_line_direct_repaint'', N''end_of_line_reject'', N''final_reject'')
    ORDER BY inspection_step, e.Sequence, e.[Part Number], h.moment_at, h.id;

    /* Current-week high-repaint summary from the EOL inspection date. */
    SELECT
        CONVERT(date, m.[Inspected Date EOL]) AS report_date,
        m.RepaintCount AS repaint_count,
        COUNT(DISTINCT m.ID) AS total
    FROM dbo.[Master Data Table] AS m
    INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = m.ID
    WHERE m.RepaintCount > 3
      AND m.[Inspected Date EOL] >= CONVERT(datetime2(0), @WeekStart)
      AND m.[Inspected Date EOL] < @WindowEndExclusive
      AND ISNULL(e.Model, N'''') <> N''Service''
    GROUP BY CONVERT(date, m.[Inspected Date EOL]), m.RepaintCount
    ORDER BY report_date, repaint_count;

    /* Current-week shipping split by line set. */
    SELECT
        CONVERT(date, e.ship_date) AS report_date,
        CASE
            WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6164%'' THEN N''N71-6164''
            WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Fender'' THEN N''FUKA''
            WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Bumper'' THEN N''Bumpers''
            WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Chassis Fairing'' THEN N''Fairings''
            ELSE N''Other''
        END AS line_set,
        COUNT(DISTINCT e.[Part ID]) AS pieces_shipped
    FROM dbo.[EDI Data Table] AS e
    WHERE e.ship_status = N''SHIPPED''
      AND e.ship_date >= CONVERT(datetime2(0), @WeekStart)
      AND e.ship_date < @WindowEndExclusive
      AND ISNULL(e.Model, N'''') <> N''Service''
    GROUP BY
        CONVERT(date, e.ship_date),
        CASE
            WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6164%'' THEN N''N71-6164''
            WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Fender'' THEN N''FUKA''
            WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Bumper'' THEN N''Bumpers''
            WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Chassis Fairing'' THEN N''Fairings''
            ELSE N''Other''
        END
    ORDER BY report_date, line_set;

    /* Previous-day high-repaint detail, sorted for review. */
    SELECT
        N''End of Line'' AS inspection_step,
        CONVERT(date, m.[Inspected Date EOL]) AS report_date,
        e.Sequence,
        e.[Part Number] AS part_number,
        e.[Part ID] AS part_id,
        e.Color,
        m.RepaintCount,
        COALESCE(NULLIF(LTRIM(RTRIM(m.[Defect Repaired])), N''''), NULLIF(LTRIM(RTRIM(m.[Defect Origin EOL])), N''''), N''Unspecified'') AS defect_description
    FROM dbo.[Master Data Table] AS m
    INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = m.ID
    WHERE m.RepaintCount > 3
      AND CONVERT(date, m.[Inspected Date EOL]) = @ReportDate
      AND ISNULL(e.Model, N'''') <> N''Service''
    ORDER BY inspection_step, e.Sequence, e.[Part Number], e.[Part ID];

    /* Aggregate selected-metric chart series. Existing KPI result sets remain in place.
       The browser contract remains aggregate-only. Loaded and Painted event totals
       use actual event hours; each distinct cart is assigned to its first event
       hour so daily totals reconcile. Staged values are point-in-time queue
       snapshots. Repaint and Finesse retain explicit numerators and denominators. */
    ;WITH HourBuckets AS (
        SELECT 0 AS bucket_number
        UNION ALL
        SELECT bucket_number + 1
        FROM HourBuckets
        WHERE bucket_number < 23
    ), DailyBuckets AS (
        SELECT DATEADD(day, -84, @WeekStart) AS report_date
        UNION ALL
        SELECT DATEADD(day, 1, report_date)
        FROM DailyBuckets
        WHERE report_date < @ReportDate
    ), DailyActivity AS (
        SELECT
            d.report_date,
            CONVERT(bit, CASE WHEN d.report_date >= @HistoryStart THEN 1 ELSE 0 END) AS data_available,
            CONVERT(bit, CASE
                WHEN d.report_date >= @HistoryStart
                 AND (
                    COALESCE(m.parts_loaded, 0) > 0
                    OR COALESCE(m.paint_processed, 0) > 0
                    OR COALESCE(m.eol_inspected, 0) > 0
                    OR COALESCE(m.receiving_total, 0) > 0
                    OR COALESCE(m.receiving_quantity, 0) > 0
                    OR COALESCE(m.final_total, 0) > 0
                    OR COALESCE(m.final_quantity, 0) > 0
                    OR COALESCE(m.parts_shipped, 0) > 0
                    OR COALESCE(m.parts_assembled, 0) > 0
                 ) THEN 1 ELSE 0
            END) AS represented_day,
            m.parts_loaded,
            m.production_parts_loaded,
            m.bv_parts_loaded,
            m.service_parts_loaded,
            m.unique_pieces_loaded,
            m.carts_loaded,
            m.production_carts_loaded,
            m.bv_carts_loaded,
            m.service_carts_loaded,
            m.paint_processed,
            m.paint_pieces_processed,
            m.pieces_scheduled,
            m.paint_fty_repaint_count,
            m.paint_fty_total,
            m.finesse_repair_count,
            m.paint_fty_repair_count,
            m.finesse_rejected_count,
            m.reject_fty_rejected_count
        FROM DailyBuckets AS d
        LEFT JOIN #DailyMetrics AS m ON m.report_date = d.report_date
    ), LoadedHourlyEvents AS (
        SELECT
            DATEPART(hour, le.loaded_at) AS bucket_number,
            COUNT_BIG(*) AS parts_loaded,
            SUM(CASE WHEN le.part_class = N''Prd'' THEN 1 ELSE 0 END) AS production_parts_loaded,
            SUM(CASE WHEN le.part_class = N''BV'' THEN 1 ELSE 0 END) AS bv_parts_loaded,
            SUM(CASE WHEN le.part_class = N''Svc'' THEN 1 ELSE 0 END) AS service_parts_loaded,
            COUNT(DISTINCT le.color_key) AS unique_colors
        FROM #LoadedEvents AS le
        WHERE le.report_date = @ReportDate
        GROUP BY DATEPART(hour, le.loaded_at)
    ), LoadedHourlyUniquePartFirst AS (
        SELECT
            le.part_id,
            DATEPART(hour, MIN(le.loaded_at)) AS bucket_number
        FROM #LoadedEvents AS le
        WHERE le.report_date = @ReportDate
        GROUP BY le.part_id
    ), LoadedHourlyUniqueParts AS (
        SELECT bucket_number, COUNT_BIG(*) AS unique_pieces_loaded
        FROM LoadedHourlyUniquePartFirst
        GROUP BY bucket_number
    ), LoadedHourlyCartFirst AS (
        SELECT
            le.PaintCart_ID,
            lc.cart_class,
            DATEPART(hour, MIN(le.loaded_at)) AS bucket_number
        FROM #LoadedEvents AS le
        INNER JOIN #LoadedCartClasses AS lc
            ON lc.report_date = le.report_date
           AND lc.PaintCart_ID = le.PaintCart_ID
        WHERE le.report_date = @ReportDate
          AND le.PaintCart_ID IS NOT NULL
        GROUP BY le.PaintCart_ID, lc.cart_class
    ), LoadedHourlyCarts AS (
        SELECT
            bucket_number,
            COUNT_BIG(*) AS carts_loaded,
            SUM(CASE WHEN cart_class = N''Prd'' THEN 1 ELSE 0 END) AS production_carts_loaded,
            SUM(CASE WHEN cart_class = N''BV'' THEN 1 ELSE 0 END) AS bv_carts_loaded,
            SUM(CASE WHEN cart_class = N''Svc'' THEN 1 ELSE 0 END) AS service_carts_loaded
        FROM LoadedHourlyCartFirst
        GROUP BY bucket_number
    ), LoadedDailyCartFirst AS (
        SELECT
            le.report_date,
            le.PaintCart_ID,
            MIN(le.loaded_at) AS cart_event_at
        FROM #LoadedEvents AS le
        WHERE le.PaintCart_ID IS NOT NULL
        GROUP BY le.report_date, le.PaintCart_ID
    ), LoadedDailyWindow AS (
        SELECT
            report_date,
            COUNT_BIG(*) AS cart_count,
            MIN(cart_event_at) AS first_event_at,
            MAX(cart_event_at) AS last_event_at,
            CONVERT(decimal(12, 3), DATEDIFF(second, MIN(cart_event_at), MAX(cart_event_at)) / 60.0) AS span_minutes
        FROM LoadedDailyCartFirst
        GROUP BY report_date
    ), LoadedDailyColors AS (
        SELECT report_date, COUNT(DISTINCT color_key) AS unique_colors
        FROM #LoadedEvents
        WHERE color_key IS NOT NULL
        GROUP BY report_date
    ), PaintedHourlyEvents AS (
        SELECT
            DATEPART(hour, pe.moment_at) AS bucket_number,
            COUNT_BIG(*) AS paint_pieces_processed,
            COUNT(DISTINCT pe.color_key) AS unique_colors
        FROM #PaintExitEvents AS pe
        WHERE pe.report_date = @ReportDate
        GROUP BY DATEPART(hour, pe.moment_at)
    ), PaintedHourlyCartFirst AS (
        SELECT
            pe.PaintCart_ID,
            DATEPART(hour, MIN(pe.moment_at)) AS bucket_number
        FROM #PaintExitEvents AS pe
        WHERE pe.report_date = @ReportDate
          AND pe.PaintCart_ID IS NOT NULL
        GROUP BY pe.PaintCart_ID
    ), PaintedHourlyCarts AS (
        SELECT bucket_number, COUNT_BIG(*) AS paint_carts
        FROM PaintedHourlyCartFirst
        GROUP BY bucket_number
    ), PaintedDailyCartFirst AS (
        SELECT
            pe.report_date,
            pe.PaintCart_ID,
            MIN(pe.moment_at) AS cart_event_at
        FROM #PaintExitEvents AS pe
        WHERE pe.PaintCart_ID IS NOT NULL
        GROUP BY pe.report_date, pe.PaintCart_ID
    ), PaintedDailyWindow AS (
        SELECT
            report_date,
            COUNT_BIG(*) AS cart_count,
            MIN(cart_event_at) AS first_event_at,
            MAX(cart_event_at) AS last_event_at,
            CONVERT(decimal(12, 3), DATEDIFF(second, MIN(cart_event_at), MAX(cart_event_at)) / 60.0) AS span_minutes
        FROM PaintedDailyCartFirst
        GROUP BY report_date
    ), PaintedDailyColors AS (
        SELECT report_date, COUNT(DISTINCT color_key) AS unique_colors
        FROM #PaintExitEvents
        WHERE color_key IS NOT NULL
        GROUP BY report_date
    ), RepaintHourly AS (
        SELECT
            DATEPART(hour, p.event_at) AS bucket_number,
            SUM(CASE WHEN p.repaint_is_initial_pass = 1 THEN p.repaint_is_failure ELSE 0 END) AS quality_numerator,
            SUM(p.repaint_is_initial_pass) AS quality_denominator
        FROM #PaintPasses AS p
        WHERE p.event_date = @ReportDate
        GROUP BY DATEPART(hour, p.event_at)
    ), FirstReceivingChart AS (
        SELECT
            h.part_id,
            h.moment_at,
            h.moment_category,
            CASE
                WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.repair_disposition))) = N''Repaired'' THEN 1
                ELSE 0
            END AS is_repaired,
            ROW_NUMBER() OVER (PARTITION BY h.part_id ORDER BY h.moment_at, h.id) AS rn
        FROM #History AS h
        INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = h.part_id
        WHERE h.moment_category IN (N''receiving_approved'', N''receiving_reject'')
    ), FinesseReceivingHourly AS (
        SELECT
            DATEPART(hour, moment_at) AS bucket_number,
            SUM(CASE WHEN moment_category = N''receiving_reject'' THEN is_repaired ELSE 0 END) AS repair_count,
            SUM(CASE WHEN moment_category = N''receiving_reject'' THEN 1 ELSE 0 END) AS rejected_count
        FROM FirstReceivingChart
        WHERE rn = 1
          AND CONVERT(date, moment_at) = @ReportDate
        GROUP BY DATEPART(hour, moment_at)
    ), FinessePaintHourly AS (
        SELECT
            DATEPART(hour, p.event_at) AS bucket_number,
            SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_finesse_repair ELSE 0 END) AS repair_count,
            SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_eol_reject ELSE 0 END) AS rejected_count
        FROM #PaintPasses AS p
        WHERE p.event_date = @ReportDate
        GROUP BY DATEPART(hour, p.event_at)
    ), ChartCutoffs AS (
        SELECT
            N''HOUR'' AS grain,
            DATEADD(hour, h.bucket_number, CONVERT(datetime2(0), @ReportDate)) AS bucket_start,
            CASE
                WHEN @ReportDate = CONVERT(date, GETDATE())
                 AND h.bucket_number = DATEPART(hour, GETDATE()) THEN CONVERT(datetime2(0), GETDATE())
                ELSE DATEADD(hour, h.bucket_number + 1, CONVERT(datetime2(0), @ReportDate))
            END AS cutoff_at,
            @ReportDate AS bucket_date,
            CONVERT(bit, CASE
                WHEN @ReportDate < CONVERT(date, GETDATE()) THEN 1
                WHEN @ReportDate = CONVERT(date, GETDATE())
                 AND h.bucket_number <= DATEPART(hour, GETDATE()) THEN 1
                ELSE 0
            END) AS data_available,
            CONVERT(bit, 1) AS represented_day,
            CONVERT(bit, CASE
                WHEN @ReportDate = CONVERT(date, GETDATE())
                 AND h.bucket_number = DATEPART(hour, GETDATE()) THEN 1 ELSE 0
            END) AS is_partial
        FROM HourBuckets AS h

        UNION ALL

        SELECT
            N''DAY'' AS grain,
            CONVERT(datetime2(0), d.report_date) AS bucket_start,
            CASE
                WHEN d.report_date = CONVERT(date, GETDATE()) THEN CONVERT(datetime2(0), GETDATE())
                ELSE DATEADD(day, 1, CONVERT(datetime2(0), d.report_date))
            END AS cutoff_at,
            d.report_date AS bucket_date,
            a.data_available,
            a.represented_day,
            CONVERT(bit, CASE WHEN d.report_date = CONVERT(date, GETDATE()) THEN 1 ELSE 0 END) AS is_partial
        FROM DailyBuckets AS d
        INNER JOIN DailyActivity AS a ON a.report_date = d.report_date
    ), PaintCartFirstScan AS (
        SELECT cp.[Cart ID] AS cart_id, MIN(cp.[Time Stamp]) AS first_paint_at
        FROM dbo.tblCarts_Paint AS cp
        WHERE cp.[Cart ID] IS NOT NULL
          AND cp.[Time Stamp] < @WindowEndExclusive
        GROUP BY cp.[Cart ID]
    ), StagedSourceParts AS (
        SELECT
            LEFT(e.[Paint Block], 3) AS block_id,
            e.cart_id,
            NULLIF(UPPER(LTRIM(RTRIM(CONVERT(nvarchar(255), e.[Color])))), N'''') AS color_key,
            e.cart_load_verified_stamp AS loaded_stamp,
            ps.first_paint_at,
            CASE
                WHEN ISNULL(e.Model, N'''') = N''Service'' THEN N''Svc''
                WHEN LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) = N''N33''
                  OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6171%'' THEN N''BV''
                ELSE N''Prd''
            END AS part_class,
            CASE
                WHEN e.insp_line_end_disposition IS NULL OR e.insp_line_end_disposition = N''Repaint'' THEN 1
                ELSE 0
            END AS is_queue_eligible,
            CASE
                WHEN ISNULL(m.RepaintCount, 0) > 0
                 AND (e.insp_line_end_disposition IS NULL OR e.insp_line_end_disposition <> N''Approved'') THEN 1
                ELSE 0
            END AS is_repaint_signal
        FROM dbo.[EDI Data Table] AS e
        LEFT JOIN dbo.[Master Data Table] AS m ON m.ID = e.[Part ID]
        LEFT JOIN PaintCartFirstScan AS ps ON ps.cart_id = e.cart_id
        WHERE e.cart_id IS NOT NULL
          AND e.Origin = N''F''
          AND ISNULL(LTRIM(RTRIM(e.[Color])), N'''') <> N''''
          AND e.[Paint Block] NOT LIKE N''Arc%''
          AND e.cart_load_verified_stamp >= DATEADD(day, -6, CONVERT(datetime2(0), DATEADD(day, -84, @WeekStart)))
          AND e.cart_load_verified_stamp < @WindowEndExclusive
    ), StagedCartState AS (
        SELECT
            c.grain,
            c.bucket_start,
            c.cutoff_at,
            c.bucket_date,
            c.data_available,
            c.represented_day,
            c.is_partial,
            s.cart_id,
            MAX(s.is_repaint_signal) AS has_repaint
        FROM ChartCutoffs AS c
        INNER JOIN StagedSourceParts AS s
            ON s.loaded_stamp >= DATEADD(day, -6, CONVERT(datetime2(0), c.bucket_date))
           AND s.loaded_stamp < c.cutoff_at
           AND (s.first_paint_at IS NULL OR s.first_paint_at >= c.cutoff_at)
        GROUP BY
            c.grain, c.bucket_start, c.cutoff_at, c.bucket_date,
            c.data_available, c.represented_day, c.is_partial, s.cart_id
    ), StagedCartGroups AS (
        SELECT
            c.grain,
            c.bucket_start,
            c.cutoff_at,
            c.bucket_date,
            c.data_available,
            c.represented_day,
            c.is_partial,
            s.block_id,
            s.cart_id,
            COUNT_BIG(*) AS piece_count,
            CASE
                WHEN MAX(CASE WHEN s.part_class = N''Svc'' THEN 1 ELSE 0 END) = 1 THEN N''Svc''
                WHEN MAX(CASE WHEN s.part_class = N''BV'' THEN 1 ELSE 0 END) = 1 THEN N''BV''
                ELSE N''Prd''
            END AS cart_class
        FROM StagedCartState AS c
        INNER JOIN StagedSourceParts AS s
            ON s.cart_id = c.cart_id
           AND s.loaded_stamp >= DATEADD(day, -6, CONVERT(datetime2(0), c.bucket_date))
           AND s.loaded_stamp < c.cutoff_at
           AND (s.first_paint_at IS NULL OR s.first_paint_at >= c.cutoff_at)
           AND s.is_queue_eligible = 1
        GROUP BY
            c.grain, c.bucket_start, c.bucket_date, c.data_available,
            c.represented_day, c.is_partial, c.cutoff_at, c.has_repaint,
            s.block_id, s.cart_id
        HAVING CONVERT(date, MIN(s.loaded_stamp)) >= DATEADD(day, -2, c.bucket_date)
            OR (c.has_repaint = 1 AND CONVERT(date, MIN(s.loaded_stamp)) >= DATEADD(day, -6, c.bucket_date))
    ), StagedTotals AS (
        SELECT
            grain,
            bucket_start,
            CONVERT(bit, MAX(CONVERT(tinyint, data_available))) AS data_available,
            CONVERT(bit, MAX(CONVERT(tinyint, represented_day))) AS represented_day,
            CONVERT(bit, MAX(CONVERT(tinyint, is_partial))) AS is_partial,
            COUNT_BIG(*) AS staged_carts,
            COALESCE(SUM(piece_count), 0) AS staged_pieces
        FROM StagedCartGroups
        GROUP BY grain, bucket_start
    ), StagedColorTotals AS (
        SELECT
            g.grain,
            g.bucket_start,
            COUNT(DISTINCT s.color_key) AS unique_colors
        FROM StagedCartGroups AS g
        INNER JOIN StagedSourceParts AS s
            ON s.block_id = g.block_id
           AND s.cart_id = g.cart_id
           AND s.loaded_stamp >= DATEADD(day, -6, CONVERT(datetime2(0), g.bucket_date))
           AND s.loaded_stamp < g.cutoff_at
           AND (s.first_paint_at IS NULL OR s.first_paint_at >= g.cutoff_at)
           AND s.is_queue_eligible = 1
        WHERE s.color_key IS NOT NULL
        GROUP BY g.grain, g.bucket_start
    ), EmptyMetric AS (
        SELECT CONVERT(bigint, 0) AS zero_count
    )
    SELECT
        N''loaded'' AS metric_key,
        N''HOUR'' AS grain,
        DATEADD(hour, h.bucket_number, CONVERT(datetime2(0), @ReportDate)) AS bucket_start,
        CONVERT(bit, CASE
            WHEN @ReportDate = CONVERT(date, GETDATE())
             AND h.bucket_number = DATEPART(hour, GETDATE()) THEN 1 ELSE 0
        END) AS is_partial,
        CONVERT(bit, 1) AS data_available,
        CONVERT(bit, 1) AS represented_day,
        COALESCE(e.parts_loaded, 0) AS parts_loaded,
        COALESCE(e.production_parts_loaded, 0) AS production_parts_loaded,
        COALESCE(e.bv_parts_loaded, 0) AS bv_parts_loaded,
        COALESCE(e.service_parts_loaded, 0) AS service_parts_loaded,
        COALESCE(u.unique_pieces_loaded, 0) AS unique_pieces_loaded,
        COALESCE(c.carts_loaded, 0) AS carts_loaded,
        COALESCE(c.production_carts_loaded, 0) AS production_carts_loaded,
        COALESCE(c.bv_carts_loaded, 0) AS bv_carts_loaded,
        COALESCE(c.service_carts_loaded, 0) AS service_carts_loaded,
        z.zero_count AS staged_carts,
        z.zero_count AS staged_pieces,
        z.zero_count AS paint_carts,
        z.zero_count AS paint_pieces_processed,
        z.zero_count AS quality_numerator,
        z.zero_count AS quality_denominator,
        CONVERT(datetime2(0), NULL) AS first_activity_at,
        CONVERT(datetime2(0), NULL) AS last_activity_at,
        CONVERT(decimal(12, 3), 0) AS activity_span_minutes,
        CONVERT(decimal(12, 3), 0) AS lunch_allowance_minutes,
        CONVERT(decimal(12, 3), 0) AS net_activity_minutes,
        CONVERT(bit, 0) AS performance_scored,
        COALESCE(e.unique_colors, 0) AS unique_colors,
        z.zero_count AS pieces_scheduled
    FROM HourBuckets AS h
    CROSS JOIN EmptyMetric AS z
    LEFT JOIN LoadedHourlyEvents AS e ON e.bucket_number = h.bucket_number
    LEFT JOIN LoadedHourlyUniqueParts AS u ON u.bucket_number = h.bucket_number
    LEFT JOIN LoadedHourlyCarts AS c ON c.bucket_number = h.bucket_number

    UNION ALL

    SELECT
        N''loaded'', N''DAY'', CONVERT(datetime2(0), a.report_date),
        CONVERT(bit, CASE WHEN a.report_date = CONVERT(date, GETDATE()) THEN 1 ELSE 0 END),
        a.data_available, a.represented_day,
        COALESCE(a.parts_loaded, 0), COALESCE(a.production_parts_loaded, 0),
        COALESCE(a.bv_parts_loaded, 0), COALESCE(a.service_parts_loaded, 0),
        COALESCE(a.unique_pieces_loaded, 0), COALESCE(a.carts_loaded, 0),
        COALESCE(a.production_carts_loaded, 0), COALESCE(a.bv_carts_loaded, 0),
        COALESCE(a.service_carts_loaded, 0),
        z.zero_count, z.zero_count, z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        w.first_event_at, w.last_event_at,
        CONVERT(decimal(12, 3), COALESCE(w.span_minutes, 0)),
        CONVERT(decimal(12, 3), CASE
            WHEN a.report_date < CONVERT(date, GETDATE())
             AND COALESCE(w.cart_count, 0) >= 2
             AND COALESCE(w.span_minutes, 0) >= 360 THEN 30 ELSE 0 END),
        CONVERT(decimal(12, 3), CASE
            WHEN COALESCE(w.cart_count, 0) < 2 THEN 0
            ELSE COALESCE(w.span_minutes, 0) - CASE
                WHEN a.report_date < CONVERT(date, GETDATE())
                 AND COALESCE(w.span_minutes, 0) >= 360 THEN 30 ELSE 0 END END),
        CONVERT(bit, CASE
            WHEN a.report_date < CONVERT(date, GETDATE())
             AND COALESCE(w.cart_count, 0) >= 2
             AND COALESCE(w.span_minutes, 0) > 0 THEN 1 ELSE 0 END),
        COALESCE(ldc.unique_colors, 0) AS unique_colors,
        z.zero_count AS pieces_scheduled
    FROM DailyActivity AS a
    CROSS JOIN EmptyMetric AS z
    LEFT JOIN LoadedDailyWindow AS w ON w.report_date = a.report_date
    LEFT JOIN LoadedDailyColors AS ldc ON ldc.report_date = a.report_date

    UNION ALL

    SELECT
        N''staged'', c.grain, c.bucket_start, c.is_partial, c.data_available, c.represented_day,
        z.zero_count, z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        COALESCE(s.staged_carts, 0), COALESCE(s.staged_pieces, 0),
        z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        CONVERT(datetime2(0), NULL), CONVERT(datetime2(0), NULL),
        CONVERT(decimal(12, 3), 0), CONVERT(decimal(12, 3), 0),
        CONVERT(decimal(12, 3), 0), CONVERT(bit, 0),
        COALESCE(sc.unique_colors, 0) AS unique_colors,
        z.zero_count AS pieces_scheduled
    FROM ChartCutoffs AS c
    CROSS JOIN EmptyMetric AS z
    LEFT JOIN StagedTotals AS s ON s.grain = c.grain AND s.bucket_start = c.bucket_start
    LEFT JOIN StagedColorTotals AS sc ON sc.grain = c.grain AND sc.bucket_start = c.bucket_start

    UNION ALL

    SELECT
        N''painted'', N''HOUR'', DATEADD(hour, h.bucket_number, CONVERT(datetime2(0), @ReportDate)),
        CONVERT(bit, CASE
            WHEN @ReportDate = CONVERT(date, GETDATE())
             AND h.bucket_number = DATEPART(hour, GETDATE()) THEN 1 ELSE 0 END),
        CONVERT(bit, 1), CONVERT(bit, 1),
        z.zero_count, z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        z.zero_count, z.zero_count,
        COALESCE(c.paint_carts, 0), COALESCE(e.paint_pieces_processed, 0),
        z.zero_count, z.zero_count,
        CONVERT(datetime2(0), NULL), CONVERT(datetime2(0), NULL),
        CONVERT(decimal(12, 3), 0), CONVERT(decimal(12, 3), 0),
        CONVERT(decimal(12, 3), 0), CONVERT(bit, 0),
        COALESCE(e.unique_colors, 0) AS unique_colors,
        z.zero_count AS pieces_scheduled
    FROM HourBuckets AS h
    CROSS JOIN EmptyMetric AS z
    LEFT JOIN PaintedHourlyEvents AS e ON e.bucket_number = h.bucket_number
    LEFT JOIN PaintedHourlyCarts AS c ON c.bucket_number = h.bucket_number

    UNION ALL

    SELECT
        N''painted'', N''DAY'', CONVERT(datetime2(0), a.report_date),
        CONVERT(bit, CASE WHEN a.report_date = CONVERT(date, GETDATE()) THEN 1 ELSE 0 END),
        a.data_available, a.represented_day,
        z.zero_count, z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        z.zero_count, z.zero_count,
        COALESCE(a.paint_processed, 0), COALESCE(a.paint_pieces_processed, 0),
        z.zero_count, z.zero_count,
        w.first_event_at, w.last_event_at,
        CONVERT(decimal(12, 3), COALESCE(w.span_minutes, 0)),
        CONVERT(decimal(12, 3), CASE
            WHEN a.report_date < CONVERT(date, GETDATE())
             AND COALESCE(w.cart_count, 0) >= 2
             AND COALESCE(w.span_minutes, 0) >= 360 THEN 30 ELSE 0 END),
        CONVERT(decimal(12, 3), CASE
            WHEN COALESCE(w.cart_count, 0) < 2 THEN 0
            ELSE COALESCE(w.span_minutes, 0) - CASE
                WHEN a.report_date < CONVERT(date, GETDATE())
                 AND COALESCE(w.span_minutes, 0) >= 360 THEN 30 ELSE 0 END END),
        CONVERT(bit, CASE
            WHEN a.report_date < CONVERT(date, GETDATE())
             AND COALESCE(w.cart_count, 0) >= 2
             AND COALESCE(w.span_minutes, 0) > 0 THEN 1 ELSE 0 END),
        COALESCE(pdc.unique_colors, 0) AS unique_colors,
        COALESCE(a.pieces_scheduled, 0) AS pieces_scheduled
    FROM DailyActivity AS a
    CROSS JOIN EmptyMetric AS z
    LEFT JOIN PaintedDailyWindow AS w ON w.report_date = a.report_date
    LEFT JOIN PaintedDailyColors AS pdc ON pdc.report_date = a.report_date

    UNION ALL

    SELECT
        N''repaint'', N''HOUR'', DATEADD(hour, h.bucket_number, CONVERT(datetime2(0), @ReportDate)),
        CONVERT(bit, CASE
            WHEN @ReportDate = CONVERT(date, GETDATE())
             AND h.bucket_number = DATEPART(hour, GETDATE()) THEN 1 ELSE 0 END),
        CONVERT(bit, 1), CONVERT(bit, 1),
        z.zero_count, z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        COALESCE(r.quality_numerator, 0), COALESCE(r.quality_denominator, 0),
        CONVERT(datetime2(0), NULL), CONVERT(datetime2(0), NULL),
        CONVERT(decimal(12, 3), 0), CONVERT(decimal(12, 3), 0),
        CONVERT(decimal(12, 3), 0), CONVERT(bit, 0),
        z.zero_count AS unique_colors,
        z.zero_count AS pieces_scheduled
    FROM HourBuckets AS h
    CROSS JOIN EmptyMetric AS z
    LEFT JOIN RepaintHourly AS r ON r.bucket_number = h.bucket_number

    UNION ALL

    SELECT
        N''repaint'', N''DAY'', CONVERT(datetime2(0), a.report_date),
        CONVERT(bit, CASE WHEN a.report_date = CONVERT(date, GETDATE()) THEN 1 ELSE 0 END),
        a.data_available, a.represented_day,
        z.zero_count, z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        COALESCE(a.paint_fty_repaint_count, 0), COALESCE(a.paint_fty_total, 0),
        CONVERT(datetime2(0), NULL), CONVERT(datetime2(0), NULL),
        CONVERT(decimal(12, 3), 0), CONVERT(decimal(12, 3), 0),
        CONVERT(decimal(12, 3), 0), CONVERT(bit, 0),
        z.zero_count AS unique_colors,
        z.zero_count AS pieces_scheduled
    FROM DailyActivity AS a
    CROSS JOIN EmptyMetric AS z

    UNION ALL

    SELECT
        N''finesse'', N''HOUR'', DATEADD(hour, h.bucket_number, CONVERT(datetime2(0), @ReportDate)),
        CONVERT(bit, CASE
            WHEN @ReportDate = CONVERT(date, GETDATE())
             AND h.bucket_number = DATEPART(hour, GETDATE()) THEN 1 ELSE 0 END),
        CONVERT(bit, 1), CONVERT(bit, 1),
        z.zero_count, z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        COALESCE(fr.repair_count, 0) + COALESCE(fp.repair_count, 0),
        COALESCE(fr.rejected_count, 0) + COALESCE(fp.rejected_count, 0),
        CONVERT(datetime2(0), NULL), CONVERT(datetime2(0), NULL),
        CONVERT(decimal(12, 3), 0), CONVERT(decimal(12, 3), 0),
        CONVERT(decimal(12, 3), 0), CONVERT(bit, 0),
        z.zero_count AS unique_colors,
        z.zero_count AS pieces_scheduled
    FROM HourBuckets AS h
    CROSS JOIN EmptyMetric AS z
    LEFT JOIN FinesseReceivingHourly AS fr ON fr.bucket_number = h.bucket_number
    LEFT JOIN FinessePaintHourly AS fp ON fp.bucket_number = h.bucket_number

    UNION ALL

    SELECT
        N''finesse'', N''DAY'', CONVERT(datetime2(0), a.report_date),
        CONVERT(bit, CASE WHEN a.report_date = CONVERT(date, GETDATE()) THEN 1 ELSE 0 END),
        a.data_available, a.represented_day,
        z.zero_count, z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        COALESCE(a.finesse_repair_count, 0) + COALESCE(a.paint_fty_repair_count, 0),
        COALESCE(a.finesse_rejected_count, 0) + COALESCE(a.reject_fty_rejected_count, 0),
        CONVERT(datetime2(0), NULL), CONVERT(datetime2(0), NULL),
        CONVERT(decimal(12, 3), 0), CONVERT(decimal(12, 3), 0),
        CONVERT(decimal(12, 3), 0), CONVERT(bit, 0),
        z.zero_count AS unique_colors,
        z.zero_count AS pieces_scheduled
    FROM DailyActivity AS a
    CROSS JOIN EmptyMetric AS z
    ORDER BY metric_key, grain DESC, bucket_start
    OPTION (MAXRECURSION 90);

    /* Aggregate-only history details. No part IDs, cart IDs, trailer IDs,
       employee data, or DriverLog rows are returned to the browser. */
    ;WITH WeekBuckets AS (
        SELECT DATEADD(day, -84, @WeekStart) AS week_start
        UNION ALL
        SELECT DATEADD(day, 7, week_start)
        FROM WeekBuckets
        WHERE week_start < @WeekStart
    ), PaintedWeeklyColors AS (
        SELECT
            w.week_start,
            COUNT(DISTINCT pe.color_key) AS value_count
        FROM WeekBuckets AS w
        LEFT JOIN #PaintExitEvents AS pe
            ON pe.report_date >= w.week_start
           AND pe.report_date < DATEADD(day, 7, w.week_start)
           AND pe.report_date <= @ReportDate
           AND pe.color_key IS NOT NULL
        GROUP BY w.week_start
    ), LoadedWeeklyColors AS (
        SELECT
            w.week_start,
            COUNT(DISTINCT le.color_key) AS value_count
        FROM WeekBuckets AS w
        LEFT JOIN #LoadedEvents AS le
            ON le.report_date >= w.week_start
           AND le.report_date < DATEADD(day, 7, w.week_start)
           AND le.report_date <= @ReportDate
           AND le.color_key IS NOT NULL
        GROUP BY w.week_start
    ), LoadedColorPartCounts AS (
        SELECT
            le.color_key AS label,
            COUNT_BIG(DISTINCT le.part_id) AS value_count
        FROM #LoadedEvents AS le
        WHERE le.report_date >= DATEADD(day, -84, @WeekStart)
          AND le.report_date <= @ReportDate
          AND le.color_key IS NOT NULL
        GROUP BY le.color_key
    ), LoadedCartSizes AS (
        SELECT
            le.report_date,
            le.PaintCart_ID,
            COUNT(DISTINCT le.part_id) AS piece_count
        FROM #LoadedEvents AS le
        WHERE le.report_date >= DATEADD(day, -84, @WeekStart)
          AND le.report_date <= @ReportDate
          AND le.PaintCart_ID IS NOT NULL
        GROUP BY le.report_date, le.PaintCart_ID
    ), LoadedEligibleCartDaily AS (
        SELECT
            report_date,
            AVG(CONVERT(decimal(18, 4), piece_count)) AS daily_average
        FROM LoadedCartSizes
        WHERE piece_count BETWEEN 1 AND 6
        GROUP BY report_date
    ), LoadedWeeklyPiecesPerCart AS (
        SELECT
            w.week_start,
            AVG(d.daily_average) AS value_count
        FROM WeekBuckets AS w
        LEFT JOIN LoadedEligibleCartDaily AS d
            ON d.report_date >= w.week_start
           AND d.report_date < DATEADD(day, 7, w.week_start)
           AND d.report_date <= @ReportDate
        GROUP BY w.week_start
    ), LoadedCartSizeDistribution AS (
        SELECT
            piece_count,
            COUNT_BIG(*) AS value_count
        FROM LoadedCartSizes
        WHERE piece_count > 0
        GROUP BY piece_count
    ), AggregateDetailRows AS (
        SELECT
            N''painted_weekly_unique_colors'' AS detail_key,
            N''painted'' AS metric_key,
            w.week_start AS bucket_start,
            CASE
                WHEN DATEADD(day, 6, w.week_start) > @ReportDate THEN @ReportDate
                ELSE DATEADD(day, 6, w.week_start)
            END AS bucket_end,
            CONVERT(nvarchar(255), NULL) AS label,
            CONVERT(decimal(18, 4), CASE WHEN w.week_start < @HistoryStart THEN NULL ELSE c.value_count END) AS value_count,
            CONVERT(bit, CASE WHEN w.week_start >= @HistoryStart THEN 1 ELSE 0 END) AS data_available,
            CONVERT(bit, CASE WHEN DATEADD(day, 6, w.week_start) > @ReportDate THEN 1 ELSE 0 END) AS is_partial,
            1 AS sort_group
        FROM WeekBuckets AS w
        INNER JOIN PaintedWeeklyColors AS c ON c.week_start = w.week_start

        UNION ALL

        SELECT
            N''loaded_weekly_unique_colors'', N''loaded'',
            w.week_start,
            CASE
                WHEN DATEADD(day, 6, w.week_start) > @ReportDate THEN @ReportDate
                ELSE DATEADD(day, 6, w.week_start)
            END,
            CONVERT(nvarchar(255), NULL),
            CONVERT(decimal(18, 4), CASE WHEN w.week_start < @HistoryStart THEN NULL ELSE c.value_count END),
            CONVERT(bit, CASE WHEN w.week_start >= @HistoryStart THEN 1 ELSE 0 END),
            CONVERT(bit, CASE WHEN DATEADD(day, 6, w.week_start) > @ReportDate THEN 1 ELSE 0 END),
            2
        FROM WeekBuckets AS w
        INNER JOIN LoadedWeeklyColors AS c ON c.week_start = w.week_start

        UNION ALL

        SELECT
            N''loaded_weekly_average_pieces_per_cart'', N''loaded'',
            w.week_start,
            CASE
                WHEN DATEADD(day, 6, w.week_start) > @ReportDate THEN @ReportDate
                ELSE DATEADD(day, 6, w.week_start)
            END,
            CONVERT(nvarchar(255), NULL),
            CONVERT(decimal(18, 4), CASE WHEN w.week_start < @HistoryStart THEN NULL ELSE p.value_count END),
            CONVERT(bit, CASE WHEN w.week_start >= @HistoryStart THEN 1 ELSE 0 END),
            CONVERT(bit, CASE WHEN DATEADD(day, 6, w.week_start) > @ReportDate THEN 1 ELSE 0 END),
            3
        FROM WeekBuckets AS w
        INNER JOIN LoadedWeeklyPiecesPerCart AS p ON p.week_start = w.week_start

        UNION ALL

        SELECT
            N''loaded_color_part_counts'', N''loaded'',
            CONVERT(date, NULL), CONVERT(date, NULL),
            c.label, CONVERT(decimal(18, 4), c.value_count), CONVERT(bit, 1), CONVERT(bit, 0), 4
        FROM LoadedColorPartCounts AS c

        UNION ALL

        SELECT
            N''loaded_cart_size_distribution'', N''loaded'',
            CONVERT(date, NULL), CONVERT(date, NULL),
            CONVERT(nvarchar(255), c.piece_count), CONVERT(decimal(18, 4), c.value_count),
            CONVERT(bit, 1), CONVERT(bit, 0), 5
        FROM LoadedCartSizeDistribution AS c
    )
    SELECT
        detail_key,
        metric_key,
        bucket_start,
        bucket_end,
        label,
        value_count,
        data_available,
        is_partial
    FROM AggregateDetailRows
    ORDER BY
        sort_group,
        CASE WHEN sort_group IN (1, 2, 3) THEN bucket_start END,
        CASE WHEN sort_group = 4 THEN value_count END DESC,
        CASE WHEN sort_group = 4 THEN label END,
        CASE WHEN sort_group = 5 THEN TRY_CONVERT(int, label) END DESC
    OPTION (MAXRECURSION 20);

    /* RESTRICTED_DRILLDOWN_RESULT_SETS_BEGIN */
    IF @IncludeRestrictedDetail = 1
    BEGIN
        /*
           Restricted result sets 16-20. These rows contain employee and part
           identifiers and are returned only when the separate identity-gated
           service explicitly opts in. The public wallboard never requests them.
        */
        DECLARE @RestrictedStart date = CASE
            WHEN DATEADD(day, -84, @WeekStart) < @HistoryStart THEN @HistoryStart
            ELSE DATEADD(day, -84, @WeekStart)
        END;

        SELECT
            pe.report_date,
            pe.part_id,
            pe.PaintCart_ID,
            pe.moment_at AS event_at,
            COALESCE(
                NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(200), session_row.PainterNameAtLogin))), N''''),
                NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(200), paint_in.Painter_Name))), N''''),
                N''Unassigned''
            ) AS painter_name,
            COALESCE(CONVERT(int, session_row.BoothNumber), 0) AS booth_number,
            pe.color_key,
            paint_in.PaintBoothSessionID,
            COALESCE(pp.repaint_is_initial_pass, 0) AS fty_total,
            CASE
                WHEN COALESCE(pp.repaint_is_initial_pass, 0) = 1
                 AND COALESCE(pp.is_finesse_repair, 0) = 0
                 AND COALESCE(pp.repaint_is_failure, 0) = 0
                 AND COALESCE(pp.repaint_is_pending, 0) = 0 THEN 1 ELSE 0
            END AS fty_approved,
            CASE
                WHEN COALESCE(pp.repaint_is_initial_pass, 0) = 1
                 AND COALESCE(pp.repaint_is_pending, 0) = 0
                 AND COALESCE(pp.repaint_is_failure, 0) = 0
                 AND COALESCE(pp.is_finesse_repair, 0) = 1 THEN 1 ELSE 0
            END AS fty_repair,
            CASE
                WHEN COALESCE(pp.repaint_is_initial_pass, 0) = 1
                 AND COALESCE(pp.repaint_is_pending, 0) = 0
                 AND COALESCE(pp.repaint_is_failure, 0) = 1 THEN 1 ELSE 0
            END AS fty_repaint,
            CASE
                WHEN COALESCE(pp.repaint_is_initial_pass, 0) = 1
                 AND COALESCE(pp.repaint_is_pending, 0) = 1 THEN 1 ELSE 0
            END AS fty_pending,
            COALESCE(pp.repaint_is_failure, 0) AS is_repaint_failure
        INTO #RestrictedPaintFacts
        FROM #PaintExitEvents AS pe
        OUTER APPLY (
            SELECT TOP (1)
                pin.Painter_Name,
                pin.PaintBoothSessionID,
                pin.TimeStamp_In
            FROM dbo.tblCarts_Paint_Oven_In AS pin
            WHERE pin.Cart_ID_In = pe.PaintCart_ID
              AND pin.TimeStamp_In IS NOT NULL
              AND pin.TimeStamp_In <= pe.moment_at
            ORDER BY pin.TimeStamp_In DESC, pin.PaintBoothSessionID DESC
        ) AS paint_in
        LEFT JOIN dbo.tblPaintBoothSessions AS session_row
            ON session_row.PaintBoothSessionID = paint_in.PaintBoothSessionID
        LEFT JOIN #PaintPasses AS pp
            ON pp.part_id = pe.part_id
           AND pp.PaintCart_ID = pe.PaintCart_ID
        WHERE pe.report_date >= @RestrictedStart
          AND pe.report_date <= @ReportDate;

        CREATE INDEX IX_RestrictedPaintFacts_DatePainter
            ON #RestrictedPaintFacts(report_date, painter_name, booth_number);
        CREATE INDEX IX_RestrictedPaintFacts_PartCart
            ON #RestrictedPaintFacts(part_id, PaintCart_ID);

        SELECT
            d.report_date,
            COALESCE(NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(200), s.PainterNameAtLogin))), N''''), N''Unassigned'') AS painter_name,
            CONVERT(int, s.BoothNumber) AS booth_number,
            SUM(CONVERT(decimal(12, 3), CASE
                WHEN overlap.session_end > overlap.session_start
                    THEN DATEDIFF(second, overlap.session_start, overlap.session_end) / 60.0
                ELSE 0
            END)) AS minutes_logged
        INTO #RestrictedPainterMinutes
        FROM #DailyMetrics AS d
        INNER JOIN dbo.tblPaintBoothSessions AS s
            ON s.SignedInAt < DATEADD(day, 1, CONVERT(datetime2(0), d.report_date))
           AND COALESCE(s.SignedOutAt, s.LastActivityAt) > CONVERT(datetime2(0), d.report_date)
        CROSS APPLY (
            SELECT
                CASE
                    WHEN s.SignedInAt < CONVERT(datetime2(0), d.report_date)
                        THEN CONVERT(datetime2(0), d.report_date)
                    ELSE s.SignedInAt
                END AS session_start,
                CASE
                    WHEN COALESCE(s.SignedOutAt, s.LastActivityAt) > DATEADD(day, 1, CONVERT(datetime2(0), d.report_date))
                        THEN DATEADD(day, 1, CONVERT(datetime2(0), d.report_date))
                    ELSE COALESCE(s.SignedOutAt, s.LastActivityAt)
                END AS session_end
        ) AS overlap
        WHERE d.report_date >= @RestrictedStart
          AND d.report_date <= @ReportDate
        GROUP BY
            d.report_date,
            COALESCE(NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(200), s.PainterNameAtLogin))), N''''), N''Unassigned''),
            CONVERT(int, s.BoothNumber);

        ;WITH PainterDaily AS (
            SELECT
                f.report_date,
                f.painter_name,
                f.booth_number,
                COUNT(DISTINCT f.PaintCart_ID) AS carts_painted,
                COUNT_BIG(*) AS parts_painted,
                COUNT(DISTINCT f.color_key) AS unique_colors,
                SUM(f.fty_total) AS fty_total,
                SUM(f.fty_approved) AS fty_approved,
                SUM(f.fty_repair) AS fty_repair,
                SUM(f.fty_repaint) AS fty_repaint,
                SUM(f.fty_pending) AS fty_pending
            FROM #RestrictedPaintFacts AS f
            GROUP BY f.report_date, f.painter_name, f.booth_number
        )
        SELECT
            p.report_date,
            p.painter_name,
            p.booth_number,
            p.carts_painted,
            p.parts_painted,
            CONVERT(decimal(12, 3), COALESCE(m.minutes_logged, 0)) AS minutes_logged,
            CONVERT(decimal(12, 4), CASE
                WHEN COALESCE(m.minutes_logged, 0) > 0
                    THEN p.parts_painted * 60.0 / m.minutes_logged
                ELSE NULL
            END) AS parts_per_hour,
            p.unique_colors,
            p.fty_total,
            p.fty_approved,
            p.fty_repair,
            p.fty_repaint,
            p.fty_pending,
            CONVERT(decimal(9, 4), CASE
                WHEN p.fty_total > 0 THEN p.fty_approved * 100.0 / p.fty_total
                ELSE NULL
            END) AS fty_percent
        FROM PainterDaily AS p
        LEFT JOIN #RestrictedPainterMinutes AS m
            ON m.report_date = p.report_date
           AND m.painter_name = p.painter_name
           AND m.booth_number = p.booth_number
        ORDER BY p.report_date, p.parts_painted DESC, p.painter_name, p.booth_number;

        ;WITH RepaintEvents AS (
            SELECT
                f.part_id,
                f.PaintCart_ID,
                f.event_at,
                f.painter_name,
                f.booth_number,
                f.color_key
            FROM #RestrictedPaintFacts AS f
            WHERE f.report_date = @ReportDate
              AND f.is_repaint_failure = 1
        ), DimensionRows AS (
            SELECT N''painter'' AS dimension, r.painter_name AS label, r.part_id
            FROM RepaintEvents AS r
            UNION ALL
            SELECT N''color'', COALESCE(NULLIF(r.color_key, N''''), N''Unknown''), r.part_id
            FROM RepaintEvents AS r
            UNION ALL
            SELECT N''booth'', CASE WHEN r.booth_number > 0 THEN N''Booth '' + CONVERT(nvarchar(12), r.booth_number) ELSE N''Unknown'' END, r.part_id
            FROM RepaintEvents AS r
        ), DimensionCounts AS (
            SELECT
                dimension,
                label,
                COUNT_BIG(*) AS repaint_events,
                COUNT(DISTINCT part_id) AS unique_parts
            FROM DimensionRows
            GROUP BY dimension, label
        )
        SELECT
            dimension,
            label,
            repaint_events,
            unique_parts,
            CONVERT(decimal(9, 4), repaint_events * 100.0 / NULLIF(SUM(repaint_events) OVER (PARTITION BY dimension), 0)) AS contribution_percent
        FROM DimensionCounts
        ORDER BY dimension, repaint_events DESC, label;

        SELECT
            f.event_at,
            f.part_id,
            NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), e.[Part Number]))), N'''') AS part_number,
            NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), e.[Sequence]))), N'''') AS sequence,
            COALESCE(NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), e.[Color]))), N''''), N''Unknown'') AS color,
            f.painter_name,
            f.booth_number,
            COALESCE(repaint_loops.repaint_loop_count, 0) AS repaint_loop_count,
            COALESCE(
                NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), defect.defect_description))), N''''),
                NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), e.insp_line_end_defect))), N''''),
                NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), e.repair_defect))), N''''),
                N''Unspecified''
            ) AS defect_description
        FROM #RestrictedPaintFacts AS f
        INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = f.part_id
        OUTER APPLY (
            SELECT COUNT_BIG(*) AS repaint_loop_count
            FROM #RepaintPassLinks AS r
            WHERE r.part_id = f.part_id
              AND r.oven_out_at <= @WindowEndExclusive
        ) AS repaint_loops
        OUTER APPLY (
            SELECT TOP (1)
                COALESCE(NULLIF(h.defect_code, N''''), NULLIF(h.moment_text, N'''')) AS defect_description
            FROM #HistoryAll AS h
            WHERE h.part_id = f.part_id
              AND h.moment_at >= f.event_at
              AND h.moment_category IN (
                  N''end_of_line_repaint'',
                  N''end_of_line_direct_repaint'',
                  N''load_line_repaint'',
                  N''repair_marked_repaint''
              )
            ORDER BY h.moment_at, h.id
        ) AS defect
        WHERE f.report_date = @ReportDate
          AND f.is_repaint_failure = 1
        ORDER BY repaint_loop_count DESC, f.event_at DESC, f.part_id;

        ;WITH RepairStarts AS (
            SELECT
                h.id AS started_id,
                h.part_id,
                h.moment_at AS started_at,
                NULLIF(LTRIM(RTRIM(h.user_name)), N'''') AS started_by,
                LEAD(h.moment_at) OVER (
                    PARTITION BY h.part_id
                    ORDER BY h.moment_at, h.id
                ) AS next_started_at
            FROM #HistoryAll AS h
            WHERE h.moment_category = N''repair_work_started''
        )
        SELECT
            CONVERT(date, COALESCE(finished.moment_at, fallback.moment_at, s.started_at)) AS report_date,
            COALESCE(
                s.started_by,
                NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(200), e.repair_user))), N''''),
                N''Unassigned''
            ) AS worker_name,
            CASE
                WHEN finished.moment_category IN (N''repair_work_repaired'', N''repair_marked_repaired'')
                  OR fallback.disposition = N''Repaired'' THEN N''repaired''
                WHEN finished.moment_category IN (N''repair_work_wfp'', N''repair_marked_repaint'', N''repair_marked_wfp'')
                  OR fallback.disposition = N''WFP'' THEN N''repaint''
                ELSE N''pending''
            END AS outcome,
            s.part_id,
            COALESCE(finished.moment_at, fallback.moment_at, s.started_at) AS event_at,
            NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), e.[Part Number]))), N'''') AS part_number,
            NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), e.[Sequence]))), N'''') AS sequence,
            COALESCE(NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), e.[Color]))), N''''), N''Unknown'') AS color,
            CONVERT(decimal(12, 3), CASE
                WHEN COALESCE(finished.moment_at, fallback.moment_at) >= s.started_at
                 AND DATEDIFF(hour, s.started_at, COALESCE(finished.moment_at, fallback.moment_at)) <= 24
                    THEN DATEDIFF(second, s.started_at, COALESCE(finished.moment_at, fallback.moment_at)) / 60.0
                ELSE NULL
            END) AS minutes_per_part,
            COALESCE(m.RepaintCount, 0) AS repaint_count
        INTO #RestrictedFinesseFacts
        FROM RepairStarts AS s
        INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = s.part_id
        LEFT JOIN dbo.[Master Data Table] AS m ON m.ID = s.part_id
        OUTER APPLY (
            SELECT TOP (1)
                h.moment_at,
                h.moment_category
            FROM #HistoryAll AS h
            WHERE h.part_id = s.part_id
              AND h.moment_at >= s.started_at
              AND (s.next_started_at IS NULL OR h.moment_at < s.next_started_at)
              AND h.moment_category IN (
                  N''repair_work_repaired'',
                  N''repair_work_wfp'',
                  N''repair_work_wfr'',
                  N''repair_marked_repaired'',
                  N''repair_marked_repaint'',
                  N''repair_marked_wfp'',
                  N''repair_marked_wfr''
              )
            ORDER BY h.moment_at, h.id
        ) AS finished
        OUTER APPLY (
            SELECT
                CASE
                    WHEN s.next_started_at IS NULL
                     AND CONVERT(datetime2(3), e.repair_stamp) >= s.started_at
                     AND DATEDIFF(hour, s.started_at, CONVERT(datetime2(3), e.repair_stamp)) <= 24
                        THEN CONVERT(datetime2(3), e.repair_stamp)
                    ELSE NULL
                END AS moment_at,
                CASE
                    WHEN s.next_started_at IS NULL
                     AND CONVERT(datetime2(3), e.repair_stamp) >= s.started_at
                     AND DATEDIFF(hour, s.started_at, CONVERT(datetime2(3), e.repair_stamp)) <= 24
                        THEN NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(32), e.repair_disposition))), N'''')
                    ELSE NULL
                END AS disposition
        ) AS fallback
        WHERE CONVERT(date, s.started_at) >= @RestrictedStart
          AND CONVERT(date, s.started_at) <= @ReportDate
          AND CONVERT(date, COALESCE(finished.moment_at, fallback.moment_at, s.started_at)) <= @ReportDate;

        CREATE INDEX IX_RestrictedFinesseFacts_DateWorker
            ON #RestrictedFinesseFacts(report_date, worker_name, outcome);

        SELECT
            report_date,
            worker_name,
            outcome,
            COUNT(DISTINCT part_id) AS part_count,
            CONVERT(decimal(12, 3), AVG(minutes_per_part)) AS average_minutes_per_part,
            MAX(repaint_count) AS max_repaint_count
        FROM #RestrictedFinesseFacts
        GROUP BY report_date, worker_name, outcome
        ORDER BY report_date, max_repaint_count DESC, part_count DESC, worker_name, outcome;

        SELECT
            event_at,
            part_id,
            part_number,
            sequence,
            color,
            worker_name,
            outcome,
            minutes_per_part,
            repaint_count
        FROM #RestrictedFinesseFacts
        WHERE report_date = @ReportDate
        ORDER BY repaint_count DESC, worker_name, part_id;

        DROP TABLE #RestrictedFinesseFacts;
        DROP TABLE #RestrictedPainterMinutes;
        DROP TABLE #RestrictedPaintFacts;
    END;
    /* RESTRICTED_DRILLDOWN_RESULT_SETS_END */

    DROP TABLE #PeriodMetrics;
    DROP TABLE #Periods;
    DROP TABLE #DailyMetrics;
    DROP TABLE #FinalFirst;
    DROP TABLE #ReceivingFirst;
    DROP TABLE #LoadedCartClasses;
    DROP TABLE #LoadedEvents;
    DROP TABLE #PaintCartClasses;
    DROP TABLE #PaintExitEvents;
    DROP TABLE #PaintPasses;
    DROP TABLE #History;
    DROP TABLE #PartClass;
    DROP TABLE #HistoryAll;
END;
';
DECLARE @ReviewedHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), @ReviewedDefinition)), 2);
IF @ReviewedHash <> @ExpectedNewHash
    THROW 54302, 'Dashboard restricted drill-down migration reviewed-definition hash mismatch.', 1;

DECLARE @CreateHeader nvarchar(256) = N'CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @AlterHeader nvarchar(256) = N'ALTER   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @CreateAt int = CHARINDEX(@CreateHeader, @ReviewedDefinition);
IF @CreateAt = 0
   OR CHARINDEX(@CreateHeader, @ReviewedDefinition, @CreateAt + 1) > 0
    THROW 54303, 'Dashboard restricted drill-down migration procedure header is not in the reviewed shape.', 1;
DECLARE @CandidateDefinition nvarchar(max) = STUFF(@ReviewedDefinition, @CreateAt, LEN(@CreateHeader), @AlterHeader);

BEGIN TRY
    IF @CommitChange = 1
    BEGIN
        BEGIN TRANSACTION;
        EXEC sys.sp_executesql @CandidateDefinition;
        DECLARE @AppliedHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
            'SHA2_256',
            CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
        ), 2);
        IF @AppliedHash <> @ExpectedNewHash
            THROW 54304, 'Dashboard restricted drill-down migration applied procedure hash mismatch.', 1;
        COMMIT TRANSACTION;
    END;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

DECLARE @FinalHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256',
    CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);
IF @CommitChange = 1 AND @FinalHash <> @ExpectedNewHash
    THROW 54305, 'Dashboard restricted drill-down migration final procedure hash mismatch.', 1;

SELECT
    @CommitChange AS commit_change,
    @ObservedOldHash AS observed_old_hash,
    @ReviewedHash AS reviewed_candidate_hash,
    @FinalHash AS final_hash;
