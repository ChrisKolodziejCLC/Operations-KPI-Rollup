/* Operations KPI quality charts: new read-only procedure.

   Creates dbo.usp_QPTS_GetOperationsQualityCharts (daily and hourly numerators, denominators, and pending counts behind the PPY,
   FTY, Receiving FTY, and Final FTY wallboard rates, plus defect counts by inspection step) and grants
   the existing read-only dashboard login EXECUTE and VIEW DEFINITION on it. No existing object is
   changed. The pass model is copied unchanged from the reviewed rollup procedure; the procedure reads
   QPTS and writes nothing but session temp tables. This script is hash-gated and reversible (see
   2026-11-19-rollback-operations-quality-charts.sql).
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @ExpectedHash varchar(64) = '480D182DB7B455C21136FE8E073FF75C9A907AB414D34E91362055A3BB3ABA64';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityCharts';

IF OBJECT_ID(@ProcedureName, N'P') IS NOT NULL
    THROW 54371, 'Quality-chart procedure already exists; refusing to replace it.', 1;
IF DATABASE_PRINCIPAL_ID(N'OperationsKpiRollup_RO') IS NULL
    THROW 54372, 'The read-only dashboard principal OperationsKpiRollup_RO was not found.', 1;

DECLARE @ReviewedDefinition nvarchar(max) = N'/*
    Read-only quality-chart series for the Operations KPI wallboard.

    Returns, for the report date and the 13 Sunday-to-Saturday weeks that end with it, the numerator,
    denominator, and pending count behind six wallboard yield rates, per day and per clock hour of the
    report date, plus the defect descriptions behind every rejection by inspection step:

      ppy_repaint   PPY, repaint basis  (numerator: passes neither repainted nor pending; denominator: all passes)
      ppy_reject    PPY, reject basis   (numerator: passes approved at end of line; denominator: all passes)
      fty_repaint   FTY, repaint basis  (initial passes only)
      fty_reject    FTY, reject basis   (initial passes only)
      receiving     Receiving FTY       (first receiving decision per part)
      final         Final FTY           (first final-inspection decision per part)

    Paint passes are dated and bucketed by the oven-exit scan; receiving and final decisions by the
    decision scan. The part history, part classification, physical-pass links, repaint ordinals, and
    pass dispositions below are copied unchanged from dbo.usp_QPTS_GetOperationsQualityShippingRollup,
    so each daily value equals the wallboard card for that date. The history starts on the governed
    event-history date 2026-09-08; earlier days are returned as unavailable.

    Result sets: 0 metadata, 1 daily series, 2 hourly series for the report date, 3 defect counts by day.

    This procedure does not write to QPTS data tables.
*/
CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsQualityCharts
    @ReportDateOverride date = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

    DECLARE @ReportDate date = COALESCE(@ReportDateOverride, DATEADD(day, -1, CONVERT(date, GETDATE())));
    -- The revised event-history method became authoritative on 2026-09-08.
    DECLARE @HistoryStart date = CONVERT(date, ''20260908'', 112);
    DECLARE @WeekStart date = DATEADD(day, -(DATEDIFF(day, CONVERT(date, ''19000107'', 112), @ReportDate) % 7), @ReportDate);
    DECLARE @ChartStart date = DATEADD(week, -12, @WeekStart);
    DECLARE @WindowEndExclusive datetime2(0) = DATEADD(day, 1, CONVERT(datetime2(0), @ReportDate));

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

    /* First receiving and first final-inspection decision per part, exactly as the rollup counts them. */
    SELECT
        h.part_id,
        h.moment_date,
        h.moment_at,
        h.moment_category,
        ROW_NUMBER() OVER (PARTITION BY h.part_id ORDER BY h.moment_at, h.id) AS rn
    INTO #FirstReceiving
    FROM #History AS h
    INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = h.part_id
    WHERE h.moment_category IN (N''receiving_approved'', N''receiving_reject'');

    SELECT
        h.part_id,
        h.moment_date,
        h.moment_at,
        h.moment_category,
        ROW_NUMBER() OVER (PARTITION BY h.part_id ORDER BY h.moment_at, h.id) AS rn
    INTO #FirstFinal
    FROM #History AS h
    INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = h.part_id
    WHERE h.moment_category IN (N''final_approved'', N''final_reject'');

    /* One fact row per pass or decision per metric. */
    SELECT
        facts.metric_key,
        facts.event_date,
        facts.event_at,
        facts.numerator,
        facts.denominator,
        facts.pending_count
    INTO #ChartFacts
    FROM (
        SELECT
            N''ppy_repaint'' AS metric_key,
            p.event_date,
            p.event_at,
            CASE WHEN p.repaint_is_pending = 0 AND p.repaint_is_failure = 0 THEN 1 ELSE 0 END AS numerator,
            1 AS denominator,
            p.repaint_is_pending AS pending_count
        FROM #PaintPasses AS p
        UNION ALL
        SELECT N''ppy_reject'', p.event_date, p.event_at, p.is_eol_approved, 1, p.is_eol_pending
        FROM #PaintPasses AS p
        UNION ALL
        SELECT
            N''fty_repaint'',
            p.event_date,
            p.event_at,
            CASE WHEN p.repaint_is_initial_pass = 1 AND p.repaint_is_pending = 0 AND p.repaint_is_failure = 0 THEN 1 ELSE 0 END,
            p.repaint_is_initial_pass,
            CASE WHEN p.repaint_is_initial_pass = 1 THEN p.repaint_is_pending ELSE 0 END
        FROM #PaintPasses AS p
        UNION ALL
        SELECT
            N''fty_reject'',
            p.event_date,
            p.event_at,
            CASE WHEN p.is_initial_pass = 1 THEN p.is_eol_approved ELSE 0 END,
            p.is_initial_pass,
            CASE WHEN p.is_initial_pass = 1 THEN p.is_eol_pending ELSE 0 END
        FROM #PaintPasses AS p
        UNION ALL
        SELECT
            N''receiving'',
            r.moment_date,
            r.moment_at,
            CASE WHEN r.moment_category = N''receiving_approved'' THEN 1 ELSE 0 END,
            1,
            0
        FROM #FirstReceiving AS r
        WHERE r.rn = 1
        UNION ALL
        SELECT
            N''final'',
            f.moment_date,
            f.moment_at,
            CASE WHEN f.moment_category = N''final_approved'' THEN 1 ELSE 0 END,
            1,
            0
        FROM #FirstFinal AS f
        WHERE f.rn = 1
    ) AS facts
    WHERE facts.event_date >= @ChartStart
      AND facts.event_date <= @ReportDate;

    CREATE INDEX IX_QualityChartFacts ON #ChartFacts(metric_key, event_date);

    /* Result set 0: metadata. */
    SELECT
        N''operations-kpi-quality-charts-v1'' AS method_version,
        @ReportDate AS report_date,
        @ChartStart AS chart_start,
        @HistoryStart AS history_start,
        (SELECT COUNT(*) FROM #ChartFacts) AS fact_rows,
        (SELECT COUNT(*) FROM #PaintPasses WHERE event_date >= @ChartStart) AS paint_passes_in_window;

    /* Result set 1: daily series. */
    ;WITH Dates AS (
        SELECT @ChartStart AS bucket_date
        UNION ALL
        SELECT DATEADD(day, 1, bucket_date) FROM Dates WHERE bucket_date < @ReportDate
    ), Metrics AS (
        SELECT N''ppy_repaint'' AS metric_key
        UNION ALL SELECT N''ppy_reject''
        UNION ALL SELECT N''fty_repaint''
        UNION ALL SELECT N''fty_reject''
        UNION ALL SELECT N''receiving''
        UNION ALL SELECT N''final''
    ), DayTotals AS (
        SELECT
            metric_key,
            event_date,
            SUM(numerator) AS numerator,
            SUM(denominator) AS denominator,
            SUM(pending_count) AS pending_count
        FROM #ChartFacts
        GROUP BY metric_key, event_date
    )
    SELECT
        m.metric_key,
        d.bucket_date AS bucket_start,
        CASE WHEN d.bucket_date >= @HistoryStart THEN 1 ELSE 0 END AS data_available,
        CASE WHEN COALESCE(t.denominator, 0) > 0 THEN 1 ELSE 0 END AS represented_day,
        COALESCE(t.numerator, 0) AS quality_numerator,
        COALESCE(t.denominator, 0) AS quality_denominator,
        COALESCE(t.pending_count, 0) AS pending_count
    FROM Dates AS d
    CROSS JOIN Metrics AS m
    LEFT JOIN DayTotals AS t ON t.metric_key = m.metric_key AND t.event_date = d.bucket_date
    ORDER BY m.metric_key, d.bucket_date
    OPTION (MAXRECURSION 400);

    /* Result set 2: hourly series for the report date. */
    ;WITH Hours AS (
        SELECT 0 AS hour_no
        UNION ALL
        SELECT hour_no + 1 FROM Hours WHERE hour_no < 23
    ), Metrics AS (
        SELECT N''ppy_repaint'' AS metric_key
        UNION ALL SELECT N''ppy_reject''
        UNION ALL SELECT N''fty_repaint''
        UNION ALL SELECT N''fty_reject''
        UNION ALL SELECT N''receiving''
        UNION ALL SELECT N''final''
    ), HourTotals AS (
        SELECT
            metric_key,
            DATEPART(hour, event_at) AS hour_no,
            SUM(numerator) AS numerator,
            SUM(denominator) AS denominator,
            SUM(pending_count) AS pending_count
        FROM #ChartFacts
        WHERE event_date = @ReportDate
        GROUP BY metric_key, DATEPART(hour, event_at)
    )
    SELECT
        m.metric_key,
        DATEADD(hour, h.hour_no, CONVERT(datetime2(0), @ReportDate)) AS bucket_start,
        1 AS data_available,
        1 AS represented_day,
        COALESCE(t.numerator, 0) AS quality_numerator,
        COALESCE(t.denominator, 0) AS quality_denominator,
        COALESCE(t.pending_count, 0) AS pending_count
    FROM Hours AS h
    CROSS JOIN Metrics AS m
    LEFT JOIN HourTotals AS t ON t.metric_key = m.metric_key AND t.hour_no = h.hour_no
    ORDER BY m.metric_key, h.hour_no;

    /* Result set 3: defect counts by day, with the same step and description mapping as the rollup. */
    SELECT
        h.moment_date AS bucket_start,
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
    WHERE h.moment_date >= @ChartStart
      AND h.moment_date <= @ReportDate
      AND h.moment_category IN (N''receiving_reject'', N''end_of_line_repair'', N''end_of_line_repaint'', N''end_of_line_direct_repaint'', N''end_of_line_reject'', N''final_reject'')
    GROUP BY
        h.moment_date,
        CASE
            WHEN h.moment_category = N''receiving_reject'' THEN N''Receiving''
            WHEN h.moment_category IN (N''end_of_line_repair'', N''end_of_line_repaint'', N''end_of_line_direct_repaint'', N''end_of_line_reject'') THEN N''End of Line''
            WHEN h.moment_category = N''final_reject'' THEN N''Final''
        END,
        COALESCE(NULLIF(LTRIM(RTRIM(d.Defect)), N''''), NULLIF(LTRIM(RTRIM(dt.[Defect Type])), N''''), NULLIF(LTRIM(RTRIM(h.defect_code)), N''''), N''Unspecified'')
    ORDER BY h.moment_date, inspection_step, defect_description;

    DROP TABLE #ChartFacts;
    DROP TABLE #FirstFinal;
    DROP TABLE #FirstReceiving;
    DROP TABLE #PaintPasses;
    DROP TABLE #History;
    DROP TABLE #PartClass;
    DROP TABLE #HistoryAll;
END;
';
DECLARE @ReviewedHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), @ReviewedDefinition)), 2);
IF @ReviewedHash <> @ExpectedHash
    THROW 54373, 'Quality-chart migration reviewed-definition hash mismatch.', 1;

BEGIN TRY
    IF @CommitChange = 1
    BEGIN
        BEGIN TRANSACTION;
        EXEC sys.sp_executesql @ReviewedDefinition;
        GRANT EXECUTE ON dbo.usp_QPTS_GetOperationsQualityCharts TO [OperationsKpiRollup_RO];
        GRANT VIEW DEFINITION ON dbo.usp_QPTS_GetOperationsQualityCharts TO [OperationsKpiRollup_RO];
        DECLARE @AppliedHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
            'SHA2_256',
            CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
        ), 2);
        IF @AppliedHash <> @ExpectedHash
            THROW 54374, 'Quality-chart migration applied procedure hash mismatch.', 1;
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
IF @CommitChange = 1 AND @FinalHash <> @ExpectedHash
    THROW 54375, 'Quality-chart migration final procedure hash mismatch.', 1;

SELECT
    @CommitChange AS commit_change,
    @ReviewedHash AS reviewed_candidate_hash,
    @FinalHash AS final_hash;
