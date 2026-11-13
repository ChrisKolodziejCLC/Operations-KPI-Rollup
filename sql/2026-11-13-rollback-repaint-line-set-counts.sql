/* Exact reverse of 2026-11-13-add-repaint-line-set-counts.sql. */
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @ExpectedOldHash varchar(64) = '80689CEC1019830F14445EB5AE5B4CBE35A9CFFB7494688BB12D8481413B0C7A';
DECLARE @ExpectedNewHash varchar(64) = '87B95E7AF33FCAE6F9FD3C9BC0D5F76D3E270ACDB1115A4E5E7C1F407A9D3422';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @OldDefinition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedOldHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@OldDefinition, N''))), 2);

IF @ExpectedOldHash IS NULL OR @ObservedOldHash <> @ExpectedOldHash
    THROW 52921, 'Dashboard repaint line-set rollback pre-change hash mismatch.', 1;

DECLARE @CandidateDefinition nvarchar(max) = @OldDefinition;
DECLARE @CreateHeader nvarchar(256) = N'CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @AlterHeader nvarchar(256) = N'ALTER   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';

IF CHARINDEX(@CreateHeader, @CandidateDefinition) > 0
    SET @CandidateDefinition = REPLACE(@CandidateDefinition, @CreateHeader, @AlterHeader);
ELSE IF CHARINDEX(@AlterHeader, @CandidateDefinition) = 0
    THROW 52922, 'Dashboard procedure header is not in the reviewed shape.', 1;

DECLARE @YieldToken nvarchar(max) = N'        pc.part_class
    INTO #YieldParts';
DECLARE @YieldReplacement nvarchar(max) = N'        pc.part_class,
        CASE
            WHEN CONVERT(nvarchar(10), e.Origin) = N''B'' THEN N''Bumpers''
            WHEN CONVERT(nvarchar(10), e.Origin) = N''F''
             AND (LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71%''
               OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N33%'') THEN N''Fairings''
            ELSE N''FUKA''
        END AS repaint_line_set
    INTO #YieldParts';
DECLARE @ClassifiedToken nvarchar(max) = N'            yp.part_class,
            CASE WHEN r.part_id IS NULL THEN 1 ELSE 0 END AS is_initial_pass,';
DECLARE @ClassifiedReplacement nvarchar(max) = N'            yp.part_class,
            yp.repaint_line_set,
            CASE WHEN r.part_id IS NULL THEN 1 ELSE 0 END AS is_initial_pass,';
DECLARE @PassToken nvarchar(max) = N'        part_class,
        is_initial_pass,';
DECLARE @PassReplacement nvarchar(max) = N'        part_class,
        repaint_line_set,
        is_initial_pass,';
DECLARE @PaintDailyToken nvarchar(max) = N'            SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_repaint_failure ELSE 0 END) AS paint_fty_repaint_count,
            COUNT(*) AS reject_ppy_total,';
DECLARE @PaintDailyReplacement nvarchar(max) = N'            SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_repaint_failure ELSE 0 END) AS paint_fty_repaint_count,
            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_repaint_failure = 1 AND p.repaint_line_set = N''FUKA'' THEN 1 ELSE 0 END) AS fuka_paint_fty_repaint_count,
            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_repaint_failure = 1 AND p.repaint_line_set = N''Bumpers'' THEN 1 ELSE 0 END) AS bumper_paint_fty_repaint_count,
            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_repaint_failure = 1 AND p.repaint_line_set = N''Fairings'' THEN 1 ELSE 0 END) AS fairing_paint_fty_repaint_count,
            COUNT(*) AS reject_ppy_total,';
DECLARE @DailyMetricToken nvarchar(max) = N'        COALESCE(p.paint_fty_repaint_count, 0) AS paint_fty_repaint_count,
        COALESCE(p.reject_ppy_total, 0) AS reject_ppy_total,';
DECLARE @DailyMetricReplacement nvarchar(max) = N'        COALESCE(p.paint_fty_repaint_count, 0) AS paint_fty_repaint_count,
        COALESCE(p.fuka_paint_fty_repaint_count, 0) AS fuka_paint_fty_repaint_count,
        COALESCE(p.bumper_paint_fty_repaint_count, 0) AS bumper_paint_fty_repaint_count,
        COALESCE(p.fairing_paint_fty_repaint_count, 0) AS fairing_paint_fty_repaint_count,
        COALESCE(p.reject_ppy_total, 0) AS reject_ppy_total,';
DECLARE @PeriodMetricToken nvarchar(max) = N'        COALESCE(SUM(d.paint_fty_repaint_count), 0) AS paint_fty_repaint_count,
        COALESCE(SUM(d.reject_ppy_total), 0) AS reject_ppy_total,';
DECLARE @PeriodMetricReplacement nvarchar(max) = N'        COALESCE(SUM(d.paint_fty_repaint_count), 0) AS paint_fty_repaint_count,
        COALESCE(SUM(d.fuka_paint_fty_repaint_count), 0) AS fuka_paint_fty_repaint_count,
        COALESCE(SUM(d.bumper_paint_fty_repaint_count), 0) AS bumper_paint_fty_repaint_count,
        COALESCE(SUM(d.fairing_paint_fty_repaint_count), 0) AS fairing_paint_fty_repaint_count,
        COALESCE(SUM(d.reject_ppy_total), 0) AS reject_ppy_total,';

IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @YieldReplacement, N''))) / LEN(@YieldReplacement) <> 1
   OR (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @ClassifiedReplacement, N''))) / LEN(@ClassifiedReplacement) <> 1
   OR (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @PassReplacement, N''))) / LEN(@PassReplacement) <> 1
   OR (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @PaintDailyReplacement, N''))) / LEN(@PaintDailyReplacement) <> 1
   OR (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @DailyMetricReplacement, N''))) / LEN(@DailyMetricReplacement) <> 1
   OR (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @PeriodMetricReplacement, N''))) / LEN(@PeriodMetricReplacement) <> 1
    THROW 52923, 'Dashboard repaint line-set rollback markers are not unique.', 1;

SET @CandidateDefinition = REPLACE(@CandidateDefinition, @YieldReplacement, @YieldToken);
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @ClassifiedReplacement, @ClassifiedToken);
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @PassReplacement, @PassToken);
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @PaintDailyReplacement, @PaintDailyToken);
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @DailyMetricReplacement, @DailyMetricToken);
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @PeriodMetricReplacement, @PeriodMetricToken);

BEGIN TRANSACTION;
EXEC sys.sp_executesql @CandidateDefinition;

DECLARE @CandidateHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256',
    CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);

IF @CandidateHash <> @ExpectedNewHash
    THROW 52924, 'Dashboard repaint line-set rollback candidate hash mismatch.', 1;

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
    THROW 52925, 'Dashboard repaint line-set rollback final hash is inconsistent with commit mode.', 1;

SELECT
    Marker = N'ASTER_OPERATIONS_KPI_REPAINT_LINE_SET_ROLLBACK_V1',
    Applied = @CommitChange,
    OldDefinitionSHA256 = @ObservedOldHash,
    CandidateDefinitionSHA256 = @CandidateHash,
    FinalDefinitionSHA256 = @FinalHash;
