/* Add aggregate chart series for Staged, Painted, Repaint, and Finesse.

   The procedure remains read-only. Existing KPI result-set indexes, headline
   formulas, permissions, and QPTS business rows are unchanged. Result set 14
   remains aggregate-only and adds metric-keyed hourly/daily rows. Staged is a
   queue snapshot; Painted is event throughput; quality rows retain numerator
   and denominator. This script is hash-gated and reversible.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @ExpectedOldHash varchar(64) = 'A7365336FFFE5170A3D963D3C4599F158C97E29B2E01FFEBD3C59A4ED817285F';
DECLARE @ExpectedNewHash varchar(64) = 'DA67E4A283C8317CC69B750B2D6636B1F76F9B6F46FF990591E82F1CA88FDD33';
DECLARE @PendingHash varchar(64) = 'PENDING_V23_CANDIDATE_SHA256';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @OldDefinition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedOldHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@OldDefinition, N''))), 2);

IF @CommitChange = 1 AND (@ExpectedOldHash = @PendingHash OR @ExpectedNewHash = @PendingHash)
    THROW 54101, 'Dashboard extended-chart migration hashes must be pinned before commit.', 1;
IF @ExpectedOldHash <> @PendingHash AND @ObservedOldHash <> @ExpectedOldHash
    THROW 54102, 'Dashboard extended-chart migration pre-change hash mismatch.', 1;

DECLARE @CandidateDefinition nvarchar(max) = @OldDefinition;
DECLARE @CreateHeader nvarchar(256) = N'CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @AlterHeader nvarchar(256) = N'ALTER   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';
IF CHARINDEX(@CreateHeader, @CandidateDefinition) > 0
    SET @CandidateDefinition = REPLACE(@CandidateDefinition, @CreateHeader, @AlterHeader);
ELSE IF CHARINDEX(@AlterHeader, @CandidateDefinition) = 0
    THROW 54103, 'Dashboard procedure header is not in the reviewed shape.', 1;

DECLARE @ChartStartMarker nvarchar(max) = N'    /* Aggregate loaded-chart series.';
DECLARE @ChartEndMarker nvarchar(max) = N'    OPTION (MAXRECURSION 90);';
DECLARE @ChartStart int = CHARINDEX(@ChartStartMarker, @CandidateDefinition);
DECLARE @ChartEnd int = CHARINDEX(@ChartEndMarker, @CandidateDefinition, @ChartStart);
IF @ChartStart = 0 OR @ChartEnd = 0
   OR CHARINDEX(@ChartStartMarker, @CandidateDefinition, @ChartStart + 1) > 0
   OR CHARINDEX(@ChartEndMarker, @CandidateDefinition, @ChartEnd + 1) > 0
    THROW 54104, 'Dashboard aggregate chart markers are not unique.', 1;

DECLARE @ChartBlock nvarchar(max) = N'    /* Aggregate selected-metric chart series. Existing KPI result sets remain in place.
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
            SUM(CASE WHEN le.part_class = N''Svc'' THEN 1 ELSE 0 END) AS service_parts_loaded
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
    ), PaintedHourlyEvents AS (
        SELECT
            DATEPART(hour, pe.moment_at) AS bucket_number,
            COUNT_BIG(*) AS paint_pieces_processed
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
        CONVERT(bit, 0) AS performance_scored
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
             AND COALESCE(w.span_minutes, 0) > 0 THEN 1 ELSE 0 END)
    FROM DailyActivity AS a
    CROSS JOIN EmptyMetric AS z
    LEFT JOIN LoadedDailyWindow AS w ON w.report_date = a.report_date

    UNION ALL

    SELECT
        N''staged'', c.grain, c.bucket_start, c.is_partial, c.data_available, c.represented_day,
        z.zero_count, z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        COALESCE(s.staged_carts, 0), COALESCE(s.staged_pieces, 0),
        z.zero_count, z.zero_count, z.zero_count, z.zero_count,
        CONVERT(datetime2(0), NULL), CONVERT(datetime2(0), NULL),
        CONVERT(decimal(12, 3), 0), CONVERT(decimal(12, 3), 0),
        CONVERT(decimal(12, 3), 0), CONVERT(bit, 0)
    FROM ChartCutoffs AS c
    CROSS JOIN EmptyMetric AS z
    LEFT JOIN StagedTotals AS s ON s.grain = c.grain AND s.bucket_start = c.bucket_start

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
        CONVERT(decimal(12, 3), 0), CONVERT(bit, 0)
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
             AND COALESCE(w.span_minutes, 0) > 0 THEN 1 ELSE 0 END)
    FROM DailyActivity AS a
    CROSS JOIN EmptyMetric AS z
    LEFT JOIN PaintedDailyWindow AS w ON w.report_date = a.report_date

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
        CONVERT(decimal(12, 3), 0), CONVERT(bit, 0)
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
        CONVERT(decimal(12, 3), 0), CONVERT(bit, 0)
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
        CONVERT(decimal(12, 3), 0), CONVERT(bit, 0)
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
        CONVERT(decimal(12, 3), 0), CONVERT(bit, 0)
    FROM DailyActivity AS a
    CROSS JOIN EmptyMetric AS z
    ORDER BY metric_key, grain DESC, bucket_start
    OPTION (MAXRECURSION 90);';
SET @CandidateDefinition = STUFF(
    @CandidateDefinition,
    @ChartStart,
    @ChartEnd + LEN(@ChartEndMarker) - @ChartStart,
    @ChartBlock
);

IF CHARINDEX(N'Aggregate selected-metric chart series', @CandidateDefinition) = 0
   OR CHARINDEX(N'Aggregate loaded-chart series', @CandidateDefinition) > 0
    THROW 54105, 'Dashboard extended-chart migration candidate is incomplete.', 1;

BEGIN TRANSACTION;
EXEC sys.sp_executesql @CandidateDefinition;
DECLARE @CandidateHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256', CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);
IF @ExpectedNewHash <> @PendingHash AND @CandidateHash <> @ExpectedNewHash
    THROW 54106, 'Dashboard extended-chart migration candidate hash mismatch.', 1;

IF @CommitChange = 1 COMMIT TRANSACTION; ELSE ROLLBACK TRANSACTION;
DECLARE @FinalHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256', CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);
IF (@CommitChange = 0 AND @FinalHash <> @ObservedOldHash)
   OR (@CommitChange = 1 AND @FinalHash <> @CandidateHash)
    THROW 54107, 'Dashboard extended-chart migration final hash is inconsistent with commit mode.', 1;

SELECT Marker = N'ASTER_OPERATIONS_KPI_EXTENDED_CHARTS_V1', Applied = @CommitChange,
       OldDefinitionSHA256 = @ObservedOldHash,
       CandidateDefinitionSHA256 = @CandidateHash,
       FinalDefinitionSHA256 = @FinalHash;
