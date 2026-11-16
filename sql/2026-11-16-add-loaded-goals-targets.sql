/* Add aggregate loading-window fields used by approved Loaded goals and targets.

   The procedure remains read-only. Existing result-set indexes, KPI formulas,
   and business rows are unchanged. Result set 14 gains only aggregate timing
   fields derived from first/last distinct-cart load events. Completed days
   spanning at least six hours receive the approved 30-minute lunch allowance;
   the current partial day is exposed but is not scored.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @ExpectedOldHash varchar(64) = 'C099469E8FC2F0C27A5B34B2A7D1AFEB27223CEA17148E0F05766D86698A57EB';
DECLARE @ExpectedNewHash varchar(64) = 'A7365336FFFE5170A3D963D3C4599F158C97E29B2E01FFEBD3C59A4ED817285F';
DECLARE @PendingHash varchar(64) = 'PENDING_V21_CANDIDATE_SHA256';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @OldDefinition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedOldHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@OldDefinition, N''))), 2);

IF @CommitChange = 1 AND (@ExpectedOldHash = @PendingHash OR @ExpectedNewHash = @PendingHash)
    THROW 53901, 'Dashboard Loaded goals/targets migration hashes must be pinned before commit.', 1;
IF @ExpectedOldHash <> @PendingHash AND @ObservedOldHash <> @ExpectedOldHash
    THROW 53902, 'Dashboard Loaded goals/targets migration pre-change hash mismatch.', 1;

DECLARE @CandidateDefinition nvarchar(max) = @OldDefinition;
DECLARE @CreateHeader nvarchar(256) = N'CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @AlterHeader nvarchar(256) = N'ALTER   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';
IF CHARINDEX(@CreateHeader, @CandidateDefinition) > 0
    SET @CandidateDefinition = REPLACE(@CandidateDefinition, @CreateHeader, @AlterHeader);
ELSE IF CHARINDEX(@AlterHeader, @CandidateDefinition) = 0
    THROW 53903, 'Dashboard procedure header is not in the reviewed shape.', 1;

DECLARE @ChartStartMarker nvarchar(max) = N'    /* Aggregate loaded-chart series.';
DECLARE @ChartEndMarker nvarchar(max) = N'    OPTION (MAXRECURSION 90);';
DECLARE @ChartStart int = CHARINDEX(@ChartStartMarker, @CandidateDefinition);
DECLARE @ChartEnd int = CHARINDEX(@ChartEndMarker, @CandidateDefinition, @ChartStart);
IF @ChartStart = 0 OR @ChartEnd = 0
   OR CHARINDEX(@ChartStartMarker, @CandidateDefinition, @ChartStart + 1) > 0
   OR CHARINDEX(@ChartEndMarker, @CandidateDefinition, @ChartEnd + 1) > 0
    THROW 53904, 'Dashboard aggregate chart markers are not unique.', 1;

DECLARE @ChartBlock nvarchar(max) = N'    /* Aggregate loaded-chart series. Existing KPI result sets remain in place.
       Event totals use actual event hours. Distinct pieces and carts use their
       first load-event hour so every hourly series reconciles to the day. */
    ;WITH HourBuckets AS (
        SELECT 0 AS bucket_number
        UNION ALL
        SELECT bucket_number + 1
        FROM HourBuckets
        WHERE bucket_number < 23
    ), HourlyEventTotals AS (
        SELECT
            DATEPART(hour, le.loaded_at) AS bucket_number,
            COUNT(*) AS parts_loaded,
            SUM(CASE WHEN le.part_class = N''Prd'' THEN 1 ELSE 0 END) AS production_parts_loaded,
            SUM(CASE WHEN le.part_class = N''BV'' THEN 1 ELSE 0 END) AS bv_parts_loaded,
            SUM(CASE WHEN le.part_class = N''Svc'' THEN 1 ELSE 0 END) AS service_parts_loaded
        FROM #LoadedEvents AS le
        WHERE le.report_date = @ReportDate
        GROUP BY DATEPART(hour, le.loaded_at)
    ), HourlyUniquePartFirst AS (
        SELECT
            le.part_id,
            DATEPART(hour, MIN(le.loaded_at)) AS bucket_number
        FROM #LoadedEvents AS le
        WHERE le.report_date = @ReportDate
        GROUP BY le.part_id
    ), HourlyUniqueParts AS (
        SELECT bucket_number, COUNT(*) AS unique_pieces_loaded
        FROM HourlyUniquePartFirst
        GROUP BY bucket_number
    ), HourlyCartFirst AS (
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
    ), HourlyCarts AS (
        SELECT
            bucket_number,
            COUNT(*) AS carts_loaded,
            SUM(CASE WHEN cart_class = N''Prd'' THEN 1 ELSE 0 END) AS production_carts_loaded,
            SUM(CASE WHEN cart_class = N''BV'' THEN 1 ELSE 0 END) AS bv_carts_loaded,
            SUM(CASE WHEN cart_class = N''Svc'' THEN 1 ELSE 0 END) AS service_carts_loaded
        FROM HourlyCartFirst
        GROUP BY bucket_number
    ), DailyCartFirst AS (
        SELECT
            le.report_date,
            le.PaintCart_ID,
            MIN(le.loaded_at) AS cart_loaded_at
        FROM #LoadedEvents AS le
        WHERE le.PaintCart_ID IS NOT NULL
        GROUP BY le.report_date, le.PaintCart_ID
    ), DailyLoadWindow AS (
        SELECT
            report_date,
            COUNT(*) AS carts_loaded,
            MIN(cart_loaded_at) AS first_cart_loaded_at,
            MAX(cart_loaded_at) AS last_cart_loaded_at,
            CONVERT(decimal(12, 3), DATEDIFF(second, MIN(cart_loaded_at), MAX(cart_loaded_at)) / 60.0) AS load_span_minutes
        FROM DailyCartFirst
        GROUP BY report_date
    ), DailyBuckets AS (
        SELECT DATEADD(day, -84, @WeekStart) AS report_date
        UNION ALL
        SELECT DATEADD(day, 1, report_date)
        FROM DailyBuckets
        WHERE report_date < @ReportDate
    )
    SELECT
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
        CONVERT(datetime2(0), NULL) AS first_cart_loaded_at,
        CONVERT(datetime2(0), NULL) AS last_cart_loaded_at,
        CONVERT(decimal(12, 3), 0) AS load_span_minutes,
        CONVERT(decimal(12, 3), 0) AS lunch_allowance_minutes,
        CONVERT(decimal(12, 3), 0) AS net_loading_minutes,
        CONVERT(bit, 0) AS performance_scored
    FROM HourBuckets AS h
    LEFT JOIN HourlyEventTotals AS e ON e.bucket_number = h.bucket_number
    LEFT JOIN HourlyUniqueParts AS u ON u.bucket_number = h.bucket_number
    LEFT JOIN HourlyCarts AS c ON c.bucket_number = h.bucket_number

    UNION ALL

    SELECT
        N''DAY'' AS grain,
        CONVERT(datetime2(0), d.report_date) AS bucket_start,
        CONVERT(bit, CASE WHEN d.report_date = CONVERT(date, GETDATE()) THEN 1 ELSE 0 END) AS is_partial,
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
        COALESCE(m.parts_loaded, 0) AS parts_loaded,
        COALESCE(m.production_parts_loaded, 0) AS production_parts_loaded,
        COALESCE(m.bv_parts_loaded, 0) AS bv_parts_loaded,
        COALESCE(m.service_parts_loaded, 0) AS service_parts_loaded,
        COALESCE(m.unique_pieces_loaded, 0) AS unique_pieces_loaded,
        COALESCE(m.carts_loaded, 0) AS carts_loaded,
        COALESCE(m.production_carts_loaded, 0) AS production_carts_loaded,
        COALESCE(m.bv_carts_loaded, 0) AS bv_carts_loaded,
        COALESCE(m.service_carts_loaded, 0) AS service_carts_loaded,
        w.first_cart_loaded_at,
        w.last_cart_loaded_at,
        CONVERT(decimal(12, 3), COALESCE(w.load_span_minutes, 0)) AS load_span_minutes,
        CONVERT(decimal(12, 3), CASE
            WHEN d.report_date < CONVERT(date, GETDATE())
             AND COALESCE(w.carts_loaded, 0) >= 2
             AND COALESCE(w.load_span_minutes, 0) >= 360 THEN 30
            ELSE 0
        END) AS lunch_allowance_minutes,
        CONVERT(decimal(12, 3), CASE
            WHEN COALESCE(w.carts_loaded, 0) < 2 THEN 0
            ELSE COALESCE(w.load_span_minutes, 0) - CASE
                WHEN d.report_date < CONVERT(date, GETDATE())
                 AND COALESCE(w.load_span_minutes, 0) >= 360 THEN 30
                ELSE 0
            END
        END) AS net_loading_minutes,
        CONVERT(bit, CASE
            WHEN d.report_date < CONVERT(date, GETDATE())
             AND COALESCE(w.carts_loaded, 0) >= 2
             AND COALESCE(w.load_span_minutes, 0) > 0 THEN 1
            ELSE 0
        END) AS performance_scored
    FROM DailyBuckets AS d
    LEFT JOIN #DailyMetrics AS m ON m.report_date = d.report_date
    LEFT JOIN DailyLoadWindow AS w ON w.report_date = d.report_date
    ORDER BY grain DESC, bucket_start
    OPTION (MAXRECURSION 90);';
SET @CandidateDefinition = STUFF(
    @CandidateDefinition,
    @ChartStart,
    @ChartEnd + LEN(@ChartEndMarker) - @ChartStart,
    @ChartBlock
);

IF CHARINDEX(N'DailyLoadWindow', @CandidateDefinition) = 0
   OR CHARINDEX(N'lunch_allowance_minutes', @CandidateDefinition) = 0
   OR CHARINDEX(N'performance_scored', @CandidateDefinition) = 0
    THROW 53905, 'Dashboard Loaded goals/targets migration candidate is incomplete.', 1;

BEGIN TRANSACTION;
EXEC sys.sp_executesql @CandidateDefinition;
DECLARE @CandidateHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256',
    CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);
IF @ExpectedNewHash <> @PendingHash AND @CandidateHash <> @ExpectedNewHash
    THROW 53906, 'Dashboard Loaded goals/targets migration candidate hash mismatch.', 1;

IF @CommitChange = 1
    COMMIT TRANSACTION;
ELSE
    ROLLBACK TRANSACTION;
DECLARE @FinalHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256',
    CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);
IF (@CommitChange = 0 AND @FinalHash <> @ObservedOldHash)
   OR (@CommitChange = 1 AND @FinalHash <> @CandidateHash)
    THROW 53907, 'Dashboard Loaded goals/targets migration final hash is inconsistent with commit mode.', 1;

SELECT
    Marker = N'ASTER_OPERATIONS_KPI_LOADED_GOALS_TARGETS_V1',
    Applied = @CommitChange,
    OldDefinitionSHA256 = @ObservedOldHash,
    CandidateDefinitionSHA256 = @CandidateHash,
    FinalDefinitionSHA256 = @FinalHash;
