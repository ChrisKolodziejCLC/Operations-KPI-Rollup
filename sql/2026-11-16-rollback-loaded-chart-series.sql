/* Exact reverse of 2026-11-16-add-loaded-chart-series.sql. */
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @ExpectedOldHash varchar(64) = '3293844115F1580DBEC0E39D0083125EB2F4517C31022E30CA54630A6F546E0A';
DECLARE @ExpectedNewHash varchar(64) = '0B45A0737682B316113771E61A64F183EC04698FCEE48AF7F8B4CC94DABB7DC3';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @OldDefinition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedOldHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@OldDefinition, N''))), 2);

IF @ObservedOldHash <> @ExpectedOldHash
    THROW 53721, 'Dashboard loaded-chart rollback pre-change hash mismatch.', 1;

DECLARE @RollbackDefinition nvarchar(max) = @OldDefinition;
DECLARE @CreateHeader nvarchar(256) = N'CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @AlterHeader nvarchar(256) = N'ALTER   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';

IF CHARINDEX(@CreateHeader, @RollbackDefinition) > 0
    SET @RollbackDefinition = REPLACE(@RollbackDefinition, @CreateHeader, @AlterHeader);
ELSE IF CHARINDEX(@AlterHeader, @RollbackDefinition) = 0
    THROW 53722, 'Dashboard rollback procedure header is not in the reviewed shape.', 1;

DECLARE @LoadedEventsToken nvarchar(max) = N'    SELECT
        h.moment_date AS report_date,
        h.moment_at AS loaded_at,
        h.part_id,
        h.PaintCart_ID,
        pc.part_class,
        pc.is_n71_6164
    INTO #LoadedEvents';
DECLARE @LoadedEventsReplacement nvarchar(max) = N'    SELECT
        h.moment_date AS report_date,
        h.part_id,
        h.PaintCart_ID,
        pc.part_class,
        pc.is_n71_6164
    INTO #LoadedEvents';

IF (LEN(@RollbackDefinition) - LEN(REPLACE(@RollbackDefinition, @LoadedEventsToken, N''))) / LEN(@LoadedEventsToken) <> 1
    THROW 53723, 'Dashboard rollback loaded-event marker is not unique.', 1;
SET @RollbackDefinition = REPLACE(@RollbackDefinition, @LoadedEventsToken, @LoadedEventsReplacement);

DECLARE @ChartStartToken nvarchar(max) = N'    /* Aggregate loaded-chart series. Existing KPI result sets remain in place.';
DECLARE @ChartEndToken nvarchar(max) = N'    DROP TABLE #PeriodMetrics;';
DECLARE @ChartStart int = CHARINDEX(@ChartStartToken, @RollbackDefinition);
DECLARE @ChartEnd int = CHARINDEX(@ChartEndToken, @RollbackDefinition, @ChartStart + 1);

IF @ChartStart = 0 OR @ChartEnd <= @ChartStart
    THROW 53724, 'Dashboard rollback chart block markers were not found.', 1;
SET @RollbackDefinition = STUFF(
    @RollbackDefinition,
    @ChartStart,
    @ChartEnd - @ChartStart,
    N''
);

IF CHARINDEX(N'h.moment_at AS loaded_at', @RollbackDefinition) > 0
   OR CHARINDEX(N'Aggregate loaded-chart series', @RollbackDefinition) > 0
   OR CHARINDEX(N'HourlyUniquePartFirst', @RollbackDefinition) > 0
   OR CHARINDEX(N'HourlyCartFirst', @RollbackDefinition) > 0
    THROW 53725, 'Dashboard loaded-chart rollback left candidate markers behind.', 1;

BEGIN TRANSACTION;
EXEC sys.sp_executesql @RollbackDefinition;

DECLARE @RollbackHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256',
    CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);

IF @RollbackHash <> @ExpectedNewHash
    THROW 53726, 'Dashboard loaded-chart rollback hash mismatch.', 1;

IF @CommitChange = 1
    COMMIT TRANSACTION;
ELSE
    ROLLBACK TRANSACTION;

DECLARE @FinalHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256',
    CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);

IF (@CommitChange = 0 AND @FinalHash <> @ExpectedOldHash)
   OR (@CommitChange = 1 AND @FinalHash <> @RollbackHash)
    THROW 53727, 'Dashboard loaded-chart rollback final hash is inconsistent with commit mode.', 1;

SELECT
    Marker = N'ASTER_OPERATIONS_KPI_LOADED_CHART_ROLLBACK_V1',
    Applied = @CommitChange,
    OldDefinitionSHA256 = @ObservedOldHash,
    RollbackDefinitionSHA256 = @RollbackHash,
    FinalDefinitionSHA256 = @FinalHash;
