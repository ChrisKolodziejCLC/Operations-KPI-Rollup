/* Reverse only the reviewed BV rollup performance optimization. */
SET NOCOUNT ON;
SET XACT_ABORT ON;
DECLARE @ExpectedCurrentHash varchar(64) = '7D1034139E5AE0A008CFD39A8403A26C260FD6AC6B1BDE758E03EAB78867D7F8';
DECLARE @ExpectedRollbackHash varchar(64) = '41F316CFBC2B882984ECF6C316EEECF2FE9A3D7EF2042FD911134054649A3BC7';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @ObservedCurrentHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))), 2);
IF @ObservedCurrentHash <> @ExpectedCurrentHash THROW 51901, 'Dashboard rollup does not match the reviewed optimization hash.', 1;
DECLARE @RollbackDefinition nvarchar(max) = N'';
SET @RollbackDefinition += N'/*
    Read-only historical rollup support for the QPTS Operations / Quality /
    Shipping report. Periods are intentionally coarse farther back and more
    detailed near the current report date:

      All prior year, Q1, Q2, prior months of the current quarter,
      prior weeks of the current month, then current-week days.

    This procedure does not write to QPTS data tables.
*/
ALTER   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup
    @ReportDateOverride date = NULL
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

    SELECT h.*
    INTO #History
    FROM #HistoryAll AS h
    WHERE NOT EXISTS (
        SELECT 1
        FROM dbo.[EDI Data Table] AS service_part
        WHERE service_part.[Part ID] = h.part_id
          AND ISNULL(service_part.Model, N'''') = N''Service''
    );

    CREATE INDEX IX_RollupHistory_PartMoment ON #History(part_id, moment_at, id);

    /* Paint pass population used for PPY and Paint FTY. */
    WITH OvenOutEvents AS (
        SELECT
            h.id AS oven_out_history_id,
            h.part_id,
            ';
SET @RollbackDefinition += N'h.PaintCart_ID,
            h.moment_at AS oven_out_at,
            ROW_NUMBER() OVER (
                PARTITION BY h.part_id, h.PaintCart_ID
                ORDER BY h.moment_at, h.id
            ) AS cart_event_rn
        FROM #HistoryAll AS h
        INNER JOIN dbo.[EDI Data Table] AS e
            ON e.[Part ID] = h.part_id
        WHERE h.moment_category = N''paint_oven_exited''
          AND h.PaintCart_ID IS NOT NULL
          AND h.PaintCart_ID > 0
          AND (CONVERT(nvarchar(8), e.[Origin]) = N''F'' OR ISNULL(e.Model, N'''') = N''Service'')
    ), OvenOut AS (
        SELECT
            oven_out_history_id,
            part_id,
            PaintCart_ID,
            oven_out_at,
            ROW_NUMBER() OVER (
                PARTITION BY part_id
                ORDER BY oven_out_at, oven_out_history_id
            ) AS paint_pass_number
        FROM OvenOutEvents
        WHERE cart_event_rn = 1
    ), FirstQualityDecision AS (
        SELECT
            o.*,
            q.quality_history_id,
            q.quality_category
        FROM OvenOut AS o
        OUTER APPLY (
            SELECT TOP (1)
                h.id AS quality_history_id,
                h.moment_category AS quality_category
            FROM #HistoryAll AS h
            WHERE h.part_id = o.part_id
              AND h.PaintCart_ID = o.PaintCart_ID
              AND h.id > o.oven_out_history_id
              AND h.moment_category IN (
                  N''end_of_line_approved'',
                  N''end_of_line_repair'',
                  N''end_of_line_repaint'',
                  N''end_of_line_direct_repaint'',
                  N''end_of_line_reject''
              )
            ORDER BY h.id
        ) AS q
    )
    SELECT
        f.part_id,
        CONVERT(date, f.oven_out_at) AS event_date,
        f.oven_out_at AS event_at,
        CASE WHEN f.paint_pass_number = 1 THEN 1 ELSE 0 END AS is_initial_pass,
        CASE WHEN f.quality_category = N''end_of_line_approved'' THEN 1 ELSE 0 END AS is_approved,
        CASE
            WHEN f.quality_category IN (N''end_of_line_repaint'', N''end_of_line_direct_repaint'') THEN 1
            WHEN EXISTS (
                SELECT 1
                FROM #HistoryAll AS r
                WHERE r.part_id = f.part_id
                  AND r.PaintCart_ID = f.PaintCart_ID
                  AND r.id > f.quality_history_id
                  AND r.moment_category IN (N''repair_marked_repaint'', N''repair_work_wfp'')
            ) THEN 1
            ELSE 0
        END AS is_repaint
    INTO #PaintPasses
    FROM FirstQualityDecision AS f
    WHERE f.quality_history_id IS NOT NULL;

    CREATE INDEX IX_RollupPaintDate ON #PaintPasses(event_date, part_id);

    /* First receiving decision per part. */
    WITH FirstReceiving AS (
        SELECT
            h.part_id,
            h.moment_date,
            h.moment_category,
            ROW_NUMBER() OVER (PARTITION BY h.part_id ORDER BY h.moment_at, h.id) AS rn
        FROM #History AS h
        WHERE h.moment_catego';
SET @RollbackDefinition += N'ry IN (N''receiving_approved'', N''receiving_reject'')
    )
    SELECT
        moment_date AS event_date,
        COUNT(*) AS receiving_total,
        SUM(CASE WHEN moment_category = N''receiving_approved'' THEN 1 ELSE 0 END) AS receiving_approved
    INTO #ReceivingFirst
    FROM FirstReceiving
    WHERE rn = 1
    GROUP BY moment_date;

    /* First final-inspection decision per part. */
    WITH FirstFinal AS (
        SELECT
            h.part_id,
            h.moment_date,
            h.moment_category,
            ROW_NUMBER() OVER (PARTITION BY h.part_id ORDER BY h.moment_at, h.id) AS rn
        FROM #History AS h
        WHERE h.moment_category IN (N''final_approved'', N''final_reject'')
    )
    SELECT
        moment_date AS event_date,
        COUNT(*) AS final_total,
        SUM(CASE WHEN moment_category = N''final_approved'' THEN 1 ELSE 0 END) AS final_approved
    INTO #FinalFirst
    FROM FirstFinal
    WHERE rn = 1
    GROUP BY moment_date;

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
    ), PaintExitEvents AS (
        SELECT
            h.moment_date AS report_date,
            h.part_id,
            h.PaintCart_ID,
            h.moment_at,
            CASE
                    WHEN ISNULL(e.Model, N'''') = N''Service'' THEN N''Svc''
                    WHEN LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) = N''N33''
                      OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6171%'' THEN N''BV''
                    ELSE N''Prd''
                END AS part_class
        FROM #HistoryAll AS h
        INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = h.part_id
        WHERE h.moment_category = N''paint_oven_exited''
          AND h.PaintCart_ID IS NOT NULL
          AND h.PaintCart_ID > 0
          AND (CONVERT(nvarchar(8), e.[Origin]) = N''F'' OR ISNULL(e.Model, N'''') = N''Service'')
    ), PaintCartClasses AS (
        SELECT
            report_date,
            PaintCart_ID,
            CASE
                WHEN MAX(CASE WHEN part_class = N''Svc'' THEN 1 ELSE 0 END) = 1 THEN N''Svc''
                WHEN MAX(CASE WHEN part_class = N''BV'' THEN 1 ELSE 0 END) = 1 THEN N''BV''
                ELSE N''Prd''
            END AS cart_class
        FROM PaintExitEvents
        GROUP BY report_date, PaintCart_ID
    ), PaintExitDaily AS (
        SELECT
            pe.report_date,
            COUNT(DISTINCT pe.PaintCart';
SET @RollbackDefinition += N'_ID) AS paint_processed,
            COUNT(DISTINCT CASE WHEN pc.cart_class = N''Prd'' THEN pe.PaintCart_ID END) AS production_paint_carts,
            COUNT(DISTINCT CASE WHEN pc.cart_class = N''BV'' THEN pe.PaintCart_ID END) AS bv_paint_carts,
            COUNT(DISTINCT CASE WHEN pc.cart_class = N''Svc'' THEN pe.PaintCart_ID END) AS service_paint_carts,
            COUNT(*) AS paint_pieces_processed,
            SUM(CASE WHEN pe.part_class = N''Prd'' THEN 1 ELSE 0 END) AS production_paint_pieces_processed,
            SUM(CASE WHEN pe.part_class = N''BV'' THEN 1 ELSE 0 END) AS bv_paint_pieces_processed,
            SUM(CASE WHEN pe.part_class = N''Svc'' THEN 1 ELSE 0 END) AS service_paint_pieces_processed,
            COUNT(DISTINCT DATEPART(hour, pe.moment_at)) AS paint_hours
        FROM PaintExitEvents AS pe
        INNER JOIN PaintCartClasses AS pc
            ON pc.report_date = pe.report_date
           AND pc.PaintCart_ID = pe.PaintCart_ID
        GROUP BY pe.report_date
    ), PaintDaily AS (
        SELECT
            p.event_date AS report_date,
            COUNT(*) AS paint_decision_pieces,
            SUM(CASE WHEN ISNULL(e.Model, N'''') <> N''Service''
                      AND LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) <> N''N33''
                      AND LTRIM(CONVERT(nvarchar(255), e.[Part Number])) NOT LIKE N''N71-6171%'' THEN 1 ELSE 0 END) AS production_paint_decision_pieces,
            SUM(CASE WHEN ISNULL(e.Model, N'''') <> N''Service''
                      AND (LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) = N''N33''
                       OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6171%'') THEN 1 ELSE 0 END) AS bv_paint_decision_pieces,
            SUM(CASE WHEN ISNULL(e.Model, N'''') = N''Service'' THEN 1 ELSE 0 END) AS service_paint_decision_pieces,
            SUM(p.is_approved) AS ppy_approved,
            SUM(CASE WHEN ISNULL(e.Model, N'''') <> N''Service''
                      AND LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) <> N''N33''
                      AND LTRIM(CONVERT(nvarchar(255), e.[Part Number])) NOT LIKE N''N71-6171%'' THEN p.is_approved ELSE 0 END) AS production_ppy_approved,
            SUM(CASE WHEN ISNULL(e.Model, N'''') <> N''Service''
                      AND (LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) = N''N33''
                       OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6171%'') THEN p.is_approved ELSE 0 END) AS bv_ppy_approved,
            SUM(CASE WHEN ISNULL(e.Model, N'''') = N''Service'' THEN p.is_approved ELSE 0 END) AS service_ppy_approved,
            SUM(p.is_repaint) AS ppy_repaint_count,
            SUM(p.is_initial_pass) AS paint_fty_total,
            SUM(CASE WHEN ISNULL(e.Model, N'''') <> N''Service''
                      AND LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) <> N''N33''
                      AND LTRIM(CONVERT(nvarchar(255), e.[Part Number])) NOT LIKE N''N71-6171%'' THEN p.is_initial_pass ELSE 0 END) AS production_paint_fty_';
SET @RollbackDefinition += N'total,
            SUM(CASE WHEN ISNULL(e.Model, N'''') <> N''Service''
                      AND (LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) = N''N33''
                       OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6171%'') THEN p.is_initial_pass ELSE 0 END) AS bv_paint_fty_total,
            SUM(CASE WHEN ISNULL(e.Model, N'''') = N''Service'' THEN p.is_initial_pass ELSE 0 END) AS service_paint_fty_total,
            SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_approved ELSE 0 END) AS paint_fty_approved,
            SUM(CASE WHEN ISNULL(e.Model, N'''') <> N''Service''
                      AND LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) <> N''N33''
                      AND LTRIM(CONVERT(nvarchar(255), e.[Part Number])) NOT LIKE N''N71-6171%''
                      AND p.is_initial_pass = 1 THEN p.is_approved ELSE 0 END) AS production_paint_fty_approved,
            SUM(CASE WHEN ISNULL(e.Model, N'''') <> N''Service''
                      AND (LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) = N''N33''
                       OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6171%'')
                      AND p.is_initial_pass = 1 THEN p.is_approved ELSE 0 END) AS bv_paint_fty_approved,
            SUM(CASE WHEN ISNULL(e.Model, N'''') = N''Service''
                      AND p.is_initial_pass = 1 THEN p.is_approved ELSE 0 END) AS service_paint_fty_approved,
            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_repaint = 1 THEN 1 ELSE 0 END) AS paint_fty_repaint_count
        FROM #PaintPasses AS p
        INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = p.part_id
        GROUP BY p.event_date
    ), LoadedEvents AS (
        SELECT
            h.moment_date AS report_date,
            h.part_id,
            h.PaintCart_ID,
            CASE
                    WHEN ISNULL(e.Model, N'''') = N''Service'' THEN N''Svc''
                    WHEN LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) = N''N33''
                      OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6171%'' THEN N''BV''
                    ELSE N''Prd''
                END AS part_class
        FROM #HistoryAll AS h
        INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = h.part_id
        WHERE h.moment_category IN (N''load_line'', N''load_line_repaint'')
    ), LoadedCartClasses AS (
        SELECT
            report_date,
            PaintCart_ID,
            CASE
                WHEN MAX(CASE WHEN part_class = N''Svc'' THEN 1 ELSE 0 END) = 1 THEN N''Svc''
                WHEN MAX(CASE WHEN part_class = N''BV'' THEN 1 ELSE 0 END) = 1 THEN N''BV''
                ELSE N''Prd''
            END AS cart_class
        FROM LoadedEvents
        WHERE PaintCart_ID IS NOT NULL
        GROUP BY report_date, PaintCart_ID
    ), LoadedDaily AS (
        SELECT
            le.report_date,
            COUNT(*) AS parts_loaded,
            SUM(CASE WHEN le.part_class = N''Prd'' THEN 1 ELSE 0 END) AS production_parts_loaded,
            SUM(CASE WHEN ';
SET @RollbackDefinition += N'le.part_class = N''BV'' THEN 1 ELSE 0 END) AS bv_parts_loaded,
            SUM(CASE WHEN le.part_class = N''Svc'' THEN 1 ELSE 0 END) AS service_parts_loaded,
            COUNT(DISTINCT le.PaintCart_ID) AS carts_loaded,
            COUNT(DISTINCT CASE WHEN lc.cart_class = N''Prd'' THEN le.PaintCart_ID END) AS production_carts_loaded,
            COUNT(DISTINCT CASE WHEN lc.cart_class = N''BV'' THEN le.PaintCart_ID END) AS bv_carts_loaded,
            COUNT(DISTINCT CASE WHEN lc.cart_class = N''Svc'' THEN le.PaintCart_ID END) AS service_carts_loaded
        FROM LoadedEvents AS le
        LEFT JOIN LoadedCartClasses AS lc
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
            COUNT(DISTINCT CASE WHEN CONVERT(nvarchar(10), e.Origin) = N''B'' THEN e.[Part ID] END) AS bumpers_shipped
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
            COUNT(DISTINCT CASE WHEN assembled.is_bumper = 1 THEN assembled.part_id END) AS assembled_bumper_count
        FROM (
            SELECT
                CONVERT(date, e.AssembledDate) AS report_date,
                e.[Part ID] AS part_id,
                CASE WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6171%'' THEN 1 ELSE 0 END AS is_bumper
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
            COUNT(*) AS complete_assy_sets
        FROM (
            SELECT
                CONVERT(date, e.Assembled';
SET @RollbackDefinition += N'Date) AS report_date,
                CONVERT(nvarchar(255), e.[Sequence]) AS sequence_id
            FROM dbo.[EDI Data Table] AS e
            WHERE e.AssembledDate >= CONVERT(datetime2(0), @HistoryStart)
              AND e.AssembledDate < @WindowEndExclusive
              AND ISNULL(e.Model, N'''') <> N''Service''
              AND LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) = N''N33''
              AND NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), e.[Sequence]))), N'''') IS NOT NULL
            GROUP BY CONVERT(date, e.AssembledDate), CONVERT(nvarchar(255), e.[Sequence])
            HAVING COUNT(DISTINCT e.[Part ID]) = 4
        ) AS complete_sets
        GROUP BY complete_sets.report_date
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
            SUM(CASE WHEN trailer_type = N''FUKA'' THEN 1 ELSE 0 END) AS fuka_trailers_pre';
SET @RollbackDefinition += N'pared,
            SUM(CASE WHEN trailer_type = N''Bumpers'' THEN 1 ELSE 0 END) AS bumper_trailers_prepared,
            SUM(CASE WHEN trailer_type = N''Fairings'' THEN 1 ELSE 0 END) AS fairing_trailers_prepared,
            SUM(CASE WHEN trailer_type = N''Other'' THEN 1 ELSE 0 END) AS other_trailers_prepared
        FROM TrailerClasses
        GROUP BY report_date
    )
    SELECT
        d.report_date,
        COALESCE(l.parts_loaded, 0) AS parts_loaded,
        COALESCE(l.production_parts_loaded, 0) AS production_parts_loaded,
        COALESCE(l.bv_parts_loaded, 0) AS bv_parts_loaded,
        COALESCE(l.service_parts_loaded, 0) AS service_parts_loaded,
        COALESCE(l.carts_loaded, 0) AS carts_loaded,
        COALESCE(l.production_carts_loaded, 0) AS production_carts_loaded,
        COALESCE(l.bv_carts_loaded, 0) AS bv_carts_loaded,
        COALESCE(l.service_carts_loaded, 0) AS service_carts_loaded,
        COALESCE(px.paint_processed, 0) AS paint_processed,
        COALESCE(px.production_paint_carts, 0) AS production_paint_carts,
        COALESCE(px.bv_paint_carts, 0) AS bv_paint_carts,
        COALESCE(px.service_paint_carts, 0) AS service_paint_carts,
        COALESCE(px.paint_pieces_processed, 0) AS paint_pieces_processed,
        COALESCE(px.production_paint_pieces_processed, 0) AS production_paint_pieces_processed,
        COALESCE(px.bv_paint_pieces_processed, 0) AS bv_paint_pieces_processed,
        COALESCE(px.service_paint_pieces_processed, 0) AS service_paint_pieces_processed,
        COALESCE(p.paint_decision_pieces, 0) AS paint_decision_pieces,
        COALESCE(p.production_paint_decision_pieces, 0) AS production_paint_decision_pieces,
        COALESCE(p.bv_paint_decision_pieces, 0) AS bv_paint_decision_pieces,
        COALESCE(p.service_paint_decision_pieces, 0) AS service_paint_decision_pieces,
        COALESCE(p.ppy_approved, 0) AS ppy_approved,
        COALESCE(p.production_ppy_approved, 0) AS production_ppy_approved,
        COALESCE(p.bv_ppy_approved, 0) AS bv_ppy_approved,
        COALESCE(p.service_ppy_approved, 0) AS service_ppy_approved,
        COALESCE(p.ppy_repaint_count, 0) AS ppy_repaint_count,
        COALESCE(p.paint_fty_total, 0) AS paint_fty_total,
        COALESCE(p.production_paint_fty_total, 0) AS production_paint_fty_total,
        COALESCE(p.bv_paint_fty_total, 0) AS bv_paint_fty_total,
        COALESCE(p.service_paint_fty_total, 0) AS service_paint_fty_total,
        COALESCE(p.paint_fty_approved, 0) AS paint_fty_approved,
        COALESCE(p.production_paint_fty_approved, 0) AS production_paint_fty_approved,
        COALESCE(p.bv_paint_fty_approved, 0) AS bv_paint_fty_approved,
        COALESCE(p.service_paint_fty_approved, 0) AS service_paint_fty_approved,
        COALESCE(p.paint_fty_repaint_count, 0) AS paint_fty_repaint_count,
        COALESCE(r.receiving_total, 0) AS receiving_total,
        COALESCE(r.receiving_approved, 0) AS receiving_approved,
        COALESCE(f.final_total, 0) AS final_total,
     ';
SET @RollbackDefinition += N'   COALESCE(f.final_approved, 0) AS final_approved,
        COALESCE(e.eol_inspected, 0) AS eol_inspected,
        COALESCE(s.parts_shipped, 0) AS parts_shipped,
        COALESCE(s.painted_parts_shipped, 0) AS painted_parts_shipped,
        COALESCE(s.bumpers_shipped, 0) AS bumpers_shipped,
        COALESCE(a.parts_assembled, 0) AS parts_assembled,
        COALESCE(ca.complete_assy_sets, 0) AS complete_assy_sets,
        COALESCE(a.assembled_bumper_count, 0) AS assembled_bumper_count,
        COALESCE(ro.receiving_repair_qty, 0) AS receiving_repair_qty,
        COALESCE(ro.receiving_repaint_qty, 0) AS receiving_repaint_qty,
        COALESCE(td.trailers_prepared, 0) AS trailers_prepared,
        COALESCE(td.fuka_trailers_prepared, 0) AS fuka_trailers_prepared,
        COALESCE(td.bumper_trailers_prepared, 0) AS bumper_trailers_prepared,
        COALESCE(td.fairing_trailers_prepared, 0) AS fairing_trailers_prepared,
        COALESCE(td.other_trailers_prepared, 0) AS other_trailers_prepared,
        s0.pieces_scheduled,
        s0.hours_scheduled,
        COALESCE(px.paint_hours, 0) AS paint_hours,
        CONVERT(decimal(10, 4), p.ppy_approved * 1.0 / NULLIF(p.paint_decision_pieces, 0)) AS ppy,
        CONVERT(decimal(10, 4), p.paint_fty_approved * 1.0 / NULLIF(p.paint_fty_total, 0)) AS paint_fty,
        CONVERT(decimal(10, 4), r.receiving_approved * 1.0 / NULLIF(r.receiving_total, 0)) AS receiving_fty,
        CONVERT(decimal(10, 4), f.final_approved * 1.0 / NULLIF(f.final_total, 0)) AS final_fty,
        CONVERT(decimal(10, 4), p.paint_fty_repaint_count * 1.0 / NULLIF(p.paint_fty_total, 0)) AS repaint_percentage,
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
                ((p.paint_fty_total - p.paint_fty_repaint_count) * 1.0';
SET @RollbackDefinition += N' / NULLIF(p.paint_fty_total, 0)) *
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
    LEFT JOIN #FinalFirst AS f ON f.event_date = d.report_date
    LEFT JOIN EolDaily AS e ON e.report_date = d.report_date
    LEFT JOIN ShipDaily AS s ON s.report_date = d.report_date
    LEFT JOIN AssemblyDaily AS a ON a.report_date = d.report_date
    LEFT JOIN CompleteAssemblyDaily AS ca ON ca.report_date = d.report_date
    LEFT JOIN ReceivingOutcomeDaily AS ro ON ro.report_date = d.report_date
    LEFT JOIN TrailerDaily AS td ON td.report_date = d.report_date
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
        FROM LongMo';
SET @RollbackDefinition += N'nthRange
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
        CASE WHEN SUM(CASE WHEN d.parts_loaded > 0 OR d.paint_processed > 0 OR d.eol_inspected > 0 OR d.receiving_total > 0 OR d.final_total > 0 OR d.parts_shipped > 0 OR d.parts_assembled > 0 THEN 1 ELSE 0 END) > 0 THEN 1 ELSE 0 ';
SET @RollbackDefinition += N'END AS data_available,
        COUNT(d.report_date) AS calendar_days,
        COUNT(CASE WHEN d.parts_loaded > 0 OR d.paint_processed > 0 OR d.eol_inspected > 0 OR d.receiving_total > 0 OR d.final_total > 0 OR d.parts_shipped > 0 OR d.parts_assembled > 0 THEN 1 END) AS data_days,
        COALESCE(SUM(d.parts_loaded), 0) AS parts_loaded,
        COALESCE(SUM(d.production_parts_loaded), 0) AS production_parts_loaded,
        COALESCE(SUM(d.bv_parts_loaded), 0) AS bv_parts_loaded,
        COALESCE(SUM(d.service_parts_loaded), 0) AS service_parts_loaded,
        COALESCE(SUM(d.carts_loaded), 0) AS carts_loaded,
        COALESCE(SUM(d.production_carts_loaded), 0) AS production_carts_loaded,
        COALESCE(SUM(d.bv_carts_loaded), 0) AS bv_carts_loaded,
        COALESCE(SUM(d.service_carts_loaded), 0) AS service_carts_loaded,
        COALESCE(SUM(d.paint_processed), 0) AS paint_processed,
        COALESCE(SUM(d.production_paint_carts), 0) AS production_paint_carts,
        COALESCE(SUM(d.bv_paint_carts), 0) AS bv_paint_carts,
        COALESCE(SUM(d.service_paint_carts), 0) AS service_paint_carts,
        COALESCE(SUM(d.paint_pieces_processed), 0) AS paint_pieces_processed,
        COALESCE(SUM(d.production_paint_pieces_processed), 0) AS production_paint_pieces_processed,
        COALESCE(SUM(d.bv_paint_pieces_processed), 0) AS bv_paint_pieces_processed,
        COALESCE(SUM(d.service_paint_pieces_processed), 0) AS service_paint_pieces_processed,
        COALESCE(SUM(d.paint_decision_pieces), 0) AS paint_decision_pieces,
        COALESCE(SUM(d.production_paint_decision_pieces), 0) AS production_paint_decision_pieces,
        COALESCE(SUM(d.bv_paint_decision_pieces), 0) AS bv_paint_decision_pieces,
        COALESCE(SUM(d.service_paint_decision_pieces), 0) AS service_paint_decision_pieces,
        COALESCE(SUM(d.ppy_approved), 0) AS ppy_approved,
        COALESCE(SUM(d.production_ppy_approved), 0) AS production_ppy_approved,
        COALESCE(SUM(d.bv_ppy_approved), 0) AS bv_ppy_approved,
        COALESCE(SUM(d.service_ppy_approved), 0) AS service_ppy_approved,
        COALESCE(SUM(d.ppy_repaint_count), 0) AS ppy_repaint_count,
        COALESCE(SUM(d.paint_fty_total), 0) AS paint_fty_total,
        COALESCE(SUM(d.production_paint_fty_total), 0) AS production_paint_fty_total,
        COALESCE(SUM(d.bv_paint_fty_total), 0) AS bv_paint_fty_total,
        COALESCE(SUM(d.service_paint_fty_total), 0) AS service_paint_fty_total,
        COALESCE(SUM(d.paint_fty_approved), 0) AS paint_fty_approved,
        COALESCE(SUM(d.production_paint_fty_approved), 0) AS production_paint_fty_approved,
        COALESCE(SUM(d.bv_paint_fty_approved), 0) AS bv_paint_fty_approved,
        COALESCE(SUM(d.service_paint_fty_approved), 0) AS service_paint_fty_approved,
        COALESCE(SUM(d.paint_fty_repaint_count), 0) AS paint_fty_repaint_count,
        COALESCE(SUM(d.receiving_total), 0) AS receiving_total,
        COALESCE(SUM(d.receiving_approved), 0) AS receiving_approved,
     ';
SET @RollbackDefinition += N'   COALESCE(SUM(d.final_total), 0) AS final_total,
        COALESCE(SUM(d.final_approved), 0) AS final_approved,
        COALESCE(SUM(d.eol_inspected), 0) AS eol_inspected,
        COALESCE(SUM(d.parts_shipped), 0) AS parts_shipped,
        COALESCE(SUM(d.painted_parts_shipped), 0) AS painted_parts_shipped,
        COALESCE(SUM(d.bumpers_shipped), 0) AS bumpers_shipped,
        COALESCE(SUM(d.parts_assembled), 0) AS parts_assembled,
        COALESCE(SUM(d.complete_assy_sets), 0) AS complete_assy_sets,
        COALESCE(SUM(d.assembled_bumper_count), 0) AS assembled_bumper_count,
        COALESCE(SUM(d.receiving_repair_qty), 0) AS receiving_repair_qty,
        COALESCE(SUM(d.receiving_repaint_qty), 0) AS receiving_repaint_qty,
        COALESCE(SUM(d.trailers_prepared), 0) AS trailers_prepared,
        COALESCE(SUM(d.fuka_trailers_prepared), 0) AS fuka_trailers_prepared,
        COALESCE(SUM(d.bumper_trailers_prepared), 0) AS bumper_trailers_prepared,
        COALESCE(SUM(d.fairing_trailers_prepared), 0) AS fairing_trailers_prepared,
        COALESCE(SUM(d.other_trailers_prepared), 0) AS other_trailers_prepared,
        COALESCE(SUM(d.pieces_scheduled), 0) AS pieces_scheduled,
        COALESCE(SUM(d.hours_scheduled), 0) AS hours_scheduled,
        COALESCE(SUM(d.paint_hours), 0) AS paint_hours,
        CONVERT(decimal(10, 4), COALESCE(SUM(d.ppy_approved), 0) * 1.0 / NULLIF(COALESCE(SUM(d.paint_decision_pieces), 0), 0)) AS ppy,
        CONVERT(decimal(10, 4), COALESCE(SUM(d.paint_fty_approved), 0) * 1.0 / NULLIF(COALESCE(SUM(d.paint_fty_total), 0), 0)) AS paint_fty,
        CONVERT(decimal(10, 4), COALESCE(SUM(d.receiving_approved), 0) * 1.0 / NULLIF(COALESCE(SUM(d.receiving_total), 0), 0)) AS receiving_fty,
        CONVERT(decimal(10, 4), COALESCE(SUM(d.final_approved), 0) * 1.0 / NULLIF(COALESCE(SUM(d.final_total), 0), 0)) AS final_fty,
        CONVERT(decimal(10, 4), COALESCE(SUM(d.paint_fty_repaint_count), 0) * 1.0 / NULLIF(COALESCE(SUM(d.paint_fty_total), 0), 0)) AS repaint_percentage,
        CONVERT(decimal(10, 4),
            CASE
                WHEN SUM(d.paint_pieces_processed) = 0 THEN NULL
                WHEN SUM(CASE WHEN d.paint_pieces_processed > 0 AND (d.pieces_scheduled IS NULL OR d.hours_scheduled IS NULL OR d.pieces_scheduled <= 0 OR d.hours_scheduled <= 0) THEN 1 ELSE 0 END) > 0 THEN NULL
                ELSE
                    CASE WHEN
                        (COALESCE(SUM(d.paint_pieces_processed), 0) * 1.0 / NULLIF(COALESCE(SUM(d.pieces_scheduled), 0), 0)) *
                        ((COALESCE(SUM(d.paint_fty_total), 0) - COALESCE(SUM(d.paint_fty_repaint_count), 0)) * 1.0 / NULLIF(COALESCE(SUM(d.paint_fty_total), 0), 0)) *
                        CASE WHEN COALESCE(SUM(d.paint_hours), 0) * 1.0 / NULLIF(COALESCE(SUM(d.hours_scheduled), 0), 0) > 1 THEN 1.0 ELSE COALESCE(SUM(d.paint_hours), 0) * 1.0 / NULLIF(COALESCE(SUM(d.hours_scheduled), 0), 0) END > 1 THEN 1.0 ELSE
                        (COALESCE(SUM(d.paint_pieces_proces';
SET @RollbackDefinition += N'sed), 0) * 1.0 / NULLIF(COALESCE(SUM(d.pieces_scheduled), 0), 0)) *
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

    /* Painter performance at daily grain. Minutes are elapsed booth-session
       minutes overlapping each calendar day, not inferred spray time. */
    ;WITH PainterParts AS (
        SELECT
            CONVERT(date, ci.PaintDate_In) AS report_date,
            COALESCE(NULLIF(LTRIM(RTRIM(pe.PainterName)), N''''), NULLIF(LTRIM(RTRIM(ci.Painter_Name)), N''''), N''Unknown'') AS painter_name,
            s.BoothNumber AS booth_number,
            COUNT(DISTINCT ci.Cart_ID_In) AS carts_paint';
SET @RollbackDefinition += N'ed,
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

    /';
SET @RollbackDefinition += N'* Top three defect descriptions by inspection step. */
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
    LEFT JOIN dbo.Defects A';
SET @RollbackDefinition += N'S d ON TRY_CONVERT(int, h.defect_code) = d.ID
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
            WHEN CONVERT(nvarchar(10), e.Origin) = N''B'' THEN N''Bumpers''
            WHEN CONVERT(nvarchar(10), e.Origin) = N''F'' AND (LTRIM(e.[Part Number]) LIKE N''N71%'' OR LTRIM(e.[Part Number]) LIKE N''N33%'') THEN N''Chassis Fairings''
            ELSE N''Fenders''
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
            WHEN CONVERT(nvarchar(10), e.Origin) = N''B'' THEN N''Bumpers''
            WHEN CONVERT(nvarchar(10), e.Origin) = N''F'' AND (LTRIM(e.[Part Number]) LIKE N''N71%'' OR LTRIM(e.[Part Number]) LIKE N''N33%'') THEN N''Chassis Fairings''
            ELSE N''Fenders''
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

    DROP TABLE #PeriodMetrics;
    DROP TABLE #Periods;
    DROP TABLE #DailyMetrics;
    DROP TAB';
SET @RollbackDefinition += N'LE #FinalFirst;
    DROP TABLE #ReceivingFirst;
    DROP TABLE #PaintPasses;
    DROP TABLE #History;
    DROP TABLE #HistoryAll;
END;
';
BEGIN TRY
    BEGIN TRANSACTION;
    EXEC sys.sp_executesql @RollbackDefinition;
    DECLARE @ObservedRollbackHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))), 2);
    IF @ObservedRollbackHash <> @ExpectedRollbackHash THROW 51902, 'Dashboard rollup optimization reverse hash mismatch.', 1;
    COMMIT TRANSACTION;
    SELECT Marker = N'ASTER_OPERATIONS_KPI_BV_OPTIMIZATION_ROLLBACK_V1', Applied = CONVERT(bit, 1),
           PreRollbackHash = @ObservedCurrentHash, RollbackHash = @ObservedRollbackHash;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
