/*
    Refine the aggregate Loaded chart contract for the 13-week trend pilot.

    Existing KPI result sets and formulas remain unchanged. Result set 14 still
    contains only aggregate HOUR and DAY rows. The DAY source window now covers
    the 13 Sunday-start weeks ending on @ReportDate and marks represented
    production days so the service can calculate honest weekly daily averages.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @ExpectedOldHash varchar(64) = '3293844115F1580DBEC0E39D0083125EB2F4517C31022E30CA54630A6F546E0A';
DECLARE @ExpectedNewHash varchar(64) = 'C099469E8FC2F0C27A5B34B2A7D1AFEB27223CEA17148E0F05766D86698A57EB';
DECLARE @PendingHash varchar(64) = 'PENDING_V20_CANDIDATE_SHA256';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @OldDefinition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedOldHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@OldDefinition, N''))), 2);

IF @ObservedOldHash <> @ExpectedOldHash
    THROW 53801, 'Dashboard 13-week chart pre-change hash mismatch.', 1;
IF @CommitChange = 1 AND @ExpectedNewHash = @PendingHash
    THROW 53802, 'Dashboard 13-week chart candidate hash must be pinned before commit.', 1;

DECLARE @CandidateDefinition nvarchar(max) = @OldDefinition;
DECLARE @CreateHeader nvarchar(256) = N'CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @AlterHeader nvarchar(256) = N'ALTER   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';

IF CHARINDEX(@CreateHeader, @CandidateDefinition) > 0
    SET @CandidateDefinition = REPLACE(@CandidateDefinition, @CreateHeader, @AlterHeader);
ELSE IF CHARINDEX(@AlterHeader, @CandidateDefinition) = 0
    THROW 53803, 'Dashboard procedure header is not in the reviewed shape.', 1;

DECLARE @OldDailyStart nvarchar(max) = N'        SELECT DATEADD(day, -29, @ReportDate) AS report_date';
DECLARE @NewDailyStart nvarchar(max) = N'        SELECT DATEADD(day, -84, @WeekStart) AS report_date';
IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @OldDailyStart, N''))) / LEN(@OldDailyStart) <> 1
    THROW 53804, 'Dashboard rolling-day start marker is not unique.', 1;
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @OldDailyStart, @NewDailyStart);

DECLARE @OldHourlyAvailability nvarchar(max) = N'        CONVERT(bit, 1) AS data_available,
        COALESCE(e.parts_loaded, 0) AS parts_loaded,';
DECLARE @NewHourlyAvailability nvarchar(max) = N'        CONVERT(bit, 1) AS data_available,
        CONVERT(bit, 1) AS represented_day,
        COALESCE(e.parts_loaded, 0) AS parts_loaded,';
IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @OldHourlyAvailability, N''))) / LEN(@OldHourlyAvailability) <> 1
    THROW 53805, 'Dashboard hourly availability marker is not unique.', 1;
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @OldHourlyAvailability, @NewHourlyAvailability);

DECLARE @OldDailyAvailability nvarchar(max) = N'        CONVERT(bit, CASE WHEN d.report_date >= @HistoryStart THEN 1 ELSE 0 END) AS data_available,
        COALESCE(m.parts_loaded, 0) AS parts_loaded,';
DECLARE @NewDailyAvailability nvarchar(max) = N'        CONVERT(bit, CASE WHEN d.report_date >= @HistoryStart THEN 1 ELSE 0 END) AS data_available,
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
        COALESCE(m.parts_loaded, 0) AS parts_loaded,';
IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @OldDailyAvailability, N''))) / LEN(@OldDailyAvailability) <> 1
    THROW 53806, 'Dashboard daily availability marker is not unique.', 1;
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @OldDailyAvailability, @NewDailyAvailability);

DECLARE @OldRecursion nvarchar(max) = N'    OPTION (MAXRECURSION 29);';
DECLARE @NewRecursion nvarchar(max) = N'    OPTION (MAXRECURSION 90);';
IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @OldRecursion, N''))) / LEN(@OldRecursion) <> 1
    THROW 53807, 'Dashboard chart recursion marker is not unique.', 1;
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @OldRecursion, @NewRecursion);

IF CHARINDEX(@NewDailyStart, @CandidateDefinition) = 0
   OR CHARINDEX(N'AS represented_day', @CandidateDefinition) = 0
   OR CHARINDEX(@NewRecursion, @CandidateDefinition) = 0
    THROW 53808, 'Dashboard 13-week chart candidate is incomplete.', 1;

BEGIN TRANSACTION;
EXEC sys.sp_executesql @CandidateDefinition;

DECLARE @CandidateHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256',
    CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);

IF @ExpectedNewHash <> @PendingHash AND @CandidateHash <> @ExpectedNewHash
    THROW 53809, 'Dashboard 13-week chart candidate hash mismatch.', 1;

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
    THROW 53810, 'Dashboard 13-week chart final hash is inconsistent with commit mode.', 1;

SELECT
    Marker = N'ASTER_OPERATIONS_KPI_LOADED_13_WEEK_V1',
    Applied = @CommitChange,
    OldDefinitionSHA256 = @ObservedOldHash,
    CandidateDefinitionSHA256 = @CandidateHash,
    FinalDefinitionSHA256 = @FinalHash;
