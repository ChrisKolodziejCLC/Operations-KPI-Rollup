/*
    Add the aggregate chart contract for the Carts / Pieces Loaded pilot.

    The existing KPI result sets and formulas are unchanged. The procedure
    appends one aggregate-only result set:
      - 24 hourly buckets for @ReportDate;
      - 30 daily buckets ending on @ReportDate.

    Event totals remain attributed to their actual load-event hour. Distinct
    pieces and carts are attributed to their first load-event hour so the
    hourly buckets reconcile exactly to the existing daily card totals.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @ExpectedOldHash varchar(64) = '0B45A0737682B316113771E61A64F183EC04698FCEE48AF7F8B4CC94DABB7DC3';
DECLARE @ExpectedNewHash varchar(64) = '3293844115F1580DBEC0E39D0083125EB2F4517C31022E30CA54630A6F546E0A';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @OldDefinition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedOldHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@OldDefinition, N''))), 2);

IF @ObservedOldHash <> @ExpectedOldHash
    THROW 53701, 'Dashboard loaded-chart pre-change hash mismatch.', 1;

DECLARE @CandidateDefinition nvarchar(max) = @OldDefinition;
DECLARE @CreateHeader nvarchar(256) = N'CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @AlterHeader nvarchar(256) = N'ALTER   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';

IF CHARINDEX(@CreateHeader, @CandidateDefinition) > 0
    SET @CandidateDefinition = REPLACE(@CandidateDefinition, @CreateHeader, @AlterHeader);
ELSE IF CHARINDEX(@AlterHeader, @CandidateDefinition) = 0
    THROW 53702, 'Dashboard procedure header is not in the reviewed shape.', 1;

DECLARE @LoadedEventsToken nvarchar(max) = N'    SELECT
        h.moment_date AS report_date,
        h.part_id,
        h.PaintCart_ID,
        pc.part_class,
        pc.is_n71_6164
    INTO #LoadedEvents';
DECLARE @LoadedEventsReplacement nvarchar(max) = N'    SELECT
        h.moment_date AS report_date,
        h.moment_at AS loaded_at,
        h.part_id,
        h.PaintCart_ID,
        pc.part_class,
        pc.is_n71_6164
    INTO #LoadedEvents';

IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @LoadedEventsToken, N''))) / LEN(@LoadedEventsToken) <> 1
    THROW 53703, 'Dashboard loaded-event marker is not unique.', 1;
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @LoadedEventsToken, @LoadedEventsReplacement);

DECLARE @ChartInsertMarker nvarchar(max) = N'    DROP TABLE #PeriodMetrics;';
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
    ), DailyBuckets AS (
        SELECT DATEADD(day, -29, @ReportDate) AS report_date
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
        COALESCE(e.parts_loaded, 0) AS parts_loaded,
        COALESCE(e.production_parts_loaded, 0) AS production_parts_loaded,
        COALESCE(e.bv_parts_loaded, 0) AS bv_parts_loaded,
        COALESCE(e.service_parts_loaded, 0) AS service_parts_loaded,
        COALESCE(u.unique_pieces_loaded, 0) AS unique_pieces_loaded,
        COALESCE(c.carts_loaded, 0) AS carts_loaded,
        COALESCE(c.production_carts_loaded, 0) AS production_carts_loaded,
        COALESCE(c.bv_carts_loaded, 0) AS bv_carts_loaded,
        COALESCE(c.service_carts_loaded, 0) AS service_carts_loaded
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
        COALESCE(m.parts_loaded, 0) AS parts_loaded,
        COALESCE(m.production_parts_loaded, 0) AS production_parts_loaded,
        COALESCE(m.bv_parts_loaded, 0) AS bv_parts_loaded,
        COALESCE(m.service_parts_loaded, 0) AS service_parts_loaded,
        COALESCE(m.unique_pieces_loaded, 0) AS unique_pieces_loaded,
        COALESCE(m.carts_loaded, 0) AS carts_loaded,
        COALESCE(m.production_carts_loaded, 0) AS production_carts_loaded,
        COALESCE(m.bv_carts_loaded, 0) AS bv_carts_loaded,
        COALESCE(m.service_carts_loaded, 0) AS service_carts_loaded
    FROM DailyBuckets AS d
    LEFT JOIN #DailyMetrics AS m ON m.report_date = d.report_date
    ORDER BY grain DESC, bucket_start
    OPTION (MAXRECURSION 29);

';

IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @ChartInsertMarker, N''))) / LEN(@ChartInsertMarker) <> 1
    THROW 53704, 'Dashboard chart insertion marker is not unique.', 1;
SET @CandidateDefinition = REPLACE(
    @CandidateDefinition,
    @ChartInsertMarker,
    @ChartBlock + @ChartInsertMarker
);

IF CHARINDEX(N'h.moment_at AS loaded_at', @CandidateDefinition) = 0
   OR CHARINDEX(N'Aggregate loaded-chart series', @CandidateDefinition) = 0
   OR CHARINDEX(N'HourlyUniquePartFirst', @CandidateDefinition) = 0
   OR CHARINDEX(N'HourlyCartFirst', @CandidateDefinition) = 0
   OR CHARINDEX(N'DATEADD(day, -29, @ReportDate)', @CandidateDefinition) = 0
    THROW 53705, 'Dashboard loaded-chart candidate is incomplete.', 1;

BEGIN TRANSACTION;
EXEC sys.sp_executesql @CandidateDefinition;

DECLARE @CandidateHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256',
    CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);

IF @CandidateHash <> @ExpectedNewHash
    THROW 53706, 'Dashboard loaded-chart candidate hash mismatch.', 1;

IF @CommitChange = 1
    COMMIT TRANSACTION;
ELSE
    ROLLBACK TRANSACTION;

DECLARE @FinalHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256',
    CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);

IF (@CommitChange = 0 AND @FinalHash <> @ExpectedOldHash)
   OR (@CommitChange = 1 AND @FinalHash <> @CandidateHash)
    THROW 53707, 'Dashboard loaded-chart final hash is inconsistent with commit mode.', 1;

SELECT
    Marker = N'ASTER_OPERATIONS_KPI_LOADED_CHART_V1',
    Applied = @CommitChange,
    OldDefinitionSHA256 = @ObservedOldHash,
    CandidateDefinitionSHA256 = @CandidateHash,
    FinalDefinitionSHA256 = @FinalHash;
