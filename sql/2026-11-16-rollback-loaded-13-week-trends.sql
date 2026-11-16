/* Restore the exact v19 Loaded chart procedure contract. */
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @ExpectedOldHash varchar(64) = 'C099469E8FC2F0C27A5B34B2A7D1AFEB27223CEA17148E0F05766D86698A57EB';
DECLARE @ExpectedNewHash varchar(64) = '3293844115F1580DBEC0E39D0083125EB2F4517C31022E30CA54630A6F546E0A';
DECLARE @PendingHash varchar(64) = 'PENDING_V20_CANDIDATE_SHA256';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @OldDefinition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedOldHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@OldDefinition, N''))), 2);

IF @CommitChange = 1 AND @ExpectedOldHash = @PendingHash
    THROW 53821, 'Dashboard 13-week rollback source hash must be pinned before commit.', 1;
IF @ExpectedOldHash <> @PendingHash AND @ObservedOldHash <> @ExpectedOldHash
    THROW 53822, 'Dashboard 13-week rollback pre-change hash mismatch.', 1;

DECLARE @CandidateDefinition nvarchar(max) = @OldDefinition;
DECLARE @CreateHeader nvarchar(256) = N'CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @AlterHeader nvarchar(256) = N'ALTER   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';

IF CHARINDEX(@CreateHeader, @CandidateDefinition) > 0
    SET @CandidateDefinition = REPLACE(@CandidateDefinition, @CreateHeader, @AlterHeader);
ELSE IF CHARINDEX(@AlterHeader, @CandidateDefinition) = 0
    THROW 53823, 'Dashboard procedure header is not in the reviewed shape.', 1;

DECLARE @NewDailyStart nvarchar(max) = N'        SELECT DATEADD(day, -84, @WeekStart) AS report_date';
DECLARE @OldDailyStart nvarchar(max) = N'        SELECT DATEADD(day, -29, @ReportDate) AS report_date';
IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @NewDailyStart, N''))) / LEN(@NewDailyStart) <> 1
    THROW 53824, 'Dashboard 13-week start marker is not unique.', 1;
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @NewDailyStart, @OldDailyStart);

DECLARE @NewHourlyAvailability nvarchar(max) = N'        CONVERT(bit, 1) AS data_available,
        CONVERT(bit, 1) AS represented_day,
        COALESCE(e.parts_loaded, 0) AS parts_loaded,';
DECLARE @OldHourlyAvailability nvarchar(max) = N'        CONVERT(bit, 1) AS data_available,
        COALESCE(e.parts_loaded, 0) AS parts_loaded,';
IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @NewHourlyAvailability, N''))) / LEN(@NewHourlyAvailability) <> 1
    THROW 53825, 'Dashboard represented-hour marker is not unique.', 1;
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @NewHourlyAvailability, @OldHourlyAvailability);

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
DECLARE @OldDailyAvailability nvarchar(max) = N'        CONVERT(bit, CASE WHEN d.report_date >= @HistoryStart THEN 1 ELSE 0 END) AS data_available,
        COALESCE(m.parts_loaded, 0) AS parts_loaded,';
IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @NewDailyAvailability, N''))) / LEN(@NewDailyAvailability) <> 1
    THROW 53826, 'Dashboard represented-day marker is not unique.', 1;
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @NewDailyAvailability, @OldDailyAvailability);

DECLARE @NewRecursion nvarchar(max) = N'    OPTION (MAXRECURSION 90);';
DECLARE @OldRecursion nvarchar(max) = N'    OPTION (MAXRECURSION 29);';
IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @NewRecursion, N''))) / LEN(@NewRecursion) <> 1
    THROW 53827, 'Dashboard 13-week recursion marker is not unique.', 1;
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @NewRecursion, @OldRecursion);

BEGIN TRANSACTION;
EXEC sys.sp_executesql @CandidateDefinition;

DECLARE @CandidateHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256',
    CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);
IF @CandidateHash <> @ExpectedNewHash
    THROW 53828, 'Dashboard 13-week rollback hash mismatch.', 1;

IF @CommitChange = 1
    COMMIT TRANSACTION;
ELSE
    ROLLBACK TRANSACTION;

DECLARE @FinalHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256',
    CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);
IF (@CommitChange = 0 AND @FinalHash <> @ObservedOldHash)
   OR (@CommitChange = 1 AND @FinalHash <> @ExpectedNewHash)
    THROW 53829, 'Dashboard 13-week rollback final hash is inconsistent with commit mode.', 1;

SELECT
    Marker = N'ASTER_OPERATIONS_KPI_LOADED_13_WEEK_ROLLBACK_V1',
    Applied = @CommitChange,
    OldDefinitionSHA256 = @ObservedOldHash,
    CandidateDefinitionSHA256 = @CandidateHash,
    FinalDefinitionSHA256 = @FinalHash;
