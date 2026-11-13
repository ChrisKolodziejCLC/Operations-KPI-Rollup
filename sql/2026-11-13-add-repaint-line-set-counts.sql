/*
    Add aggregate FUKA / Bumpers / Fairings counts for the existing
    initial-pass repaint cohort. This does not change repaint formulas,
    expose part detail, or write QPTS business rows.

    FUKA is the existing shipping Fenders bucket renamed for the wallboard:
      - Origin B => Bumpers
      - Origin F with N71/N33 part number => Fairings
      - all remaining paint-scope parts => FUKA

    Preview with @CommitChange = 0, pin @ExpectedNewHash, then switch both
    this script and its exact reverse migration to apply mode for cutover.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @ExpectedOldHash varchar(64) = '87B95E7AF33FCAE6F9FD3C9BC0D5F76D3E270ACDB1115A4E5E7C1F407A9D3422';
DECLARE @ExpectedNewHash varchar(64) = '80689CEC1019830F14445EB5AE5B4CBE35A9CFFB7494688BB12D8481413B0C7A';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @OldDefinition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedOldHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@OldDefinition, N''))), 2);

IF @ObservedOldHash <> @ExpectedOldHash
    THROW 52901, 'Dashboard repaint line-set pre-change hash mismatch.', 1;

DECLARE @CandidateDefinition nvarchar(max) = @OldDefinition;
DECLARE @CreateHeader nvarchar(256) = N'CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @AlterHeader nvarchar(256) = N'ALTER   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';

IF CHARINDEX(@CreateHeader, @CandidateDefinition) > 0
    SET @CandidateDefinition = REPLACE(@CandidateDefinition, @CreateHeader, @AlterHeader);
ELSE IF CHARINDEX(@AlterHeader, @CandidateDefinition) = 0
    THROW 52902, 'Dashboard procedure header is not in the reviewed shape.', 1;

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

IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @YieldToken, N''))) / LEN(@YieldToken) <> 1
    THROW 52903, 'Dashboard YieldParts marker is not unique.', 1;
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @YieldToken, @YieldReplacement);

DECLARE @ClassifiedToken nvarchar(max) = N'            yp.part_class,
            CASE WHEN r.part_id IS NULL THEN 1 ELSE 0 END AS is_initial_pass,';
DECLARE @ClassifiedReplacement nvarchar(max) = N'            yp.part_class,
            yp.repaint_line_set,
            CASE WHEN r.part_id IS NULL THEN 1 ELSE 0 END AS is_initial_pass,';

IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @ClassifiedToken, N''))) / LEN(@ClassifiedToken) <> 1
    THROW 52904, 'Dashboard ClassifiedPasses marker is not unique.', 1;
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @ClassifiedToken, @ClassifiedReplacement);

DECLARE @PassToken nvarchar(max) = N'        part_class,
        is_initial_pass,';
DECLARE @PassReplacement nvarchar(max) = N'        part_class,
        repaint_line_set,
        is_initial_pass,';

IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @PassToken, N''))) / LEN(@PassToken) <> 1
    THROW 52905, 'Dashboard PaintPasses marker is not unique.', 1;
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @PassToken, @PassReplacement);

DECLARE @PaintDailyToken nvarchar(max) = N'            SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_repaint_failure ELSE 0 END) AS paint_fty_repaint_count,
            COUNT(*) AS reject_ppy_total,';
DECLARE @PaintDailyReplacement nvarchar(max) = N'            SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_repaint_failure ELSE 0 END) AS paint_fty_repaint_count,
            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_repaint_failure = 1 AND p.repaint_line_set = N''FUKA'' THEN 1 ELSE 0 END) AS fuka_paint_fty_repaint_count,
            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_repaint_failure = 1 AND p.repaint_line_set = N''Bumpers'' THEN 1 ELSE 0 END) AS bumper_paint_fty_repaint_count,
            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_repaint_failure = 1 AND p.repaint_line_set = N''Fairings'' THEN 1 ELSE 0 END) AS fairing_paint_fty_repaint_count,
            COUNT(*) AS reject_ppy_total,';

IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @PaintDailyToken, N''))) / LEN(@PaintDailyToken) <> 1
    THROW 52906, 'Dashboard PaintDaily repaint marker is not unique.', 1;
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @PaintDailyToken, @PaintDailyReplacement);

DECLARE @DailyMetricToken nvarchar(max) = N'        COALESCE(p.paint_fty_repaint_count, 0) AS paint_fty_repaint_count,
        COALESCE(p.reject_ppy_total, 0) AS reject_ppy_total,';
DECLARE @DailyMetricReplacement nvarchar(max) = N'        COALESCE(p.paint_fty_repaint_count, 0) AS paint_fty_repaint_count,
        COALESCE(p.fuka_paint_fty_repaint_count, 0) AS fuka_paint_fty_repaint_count,
        COALESCE(p.bumper_paint_fty_repaint_count, 0) AS bumper_paint_fty_repaint_count,
        COALESCE(p.fairing_paint_fty_repaint_count, 0) AS fairing_paint_fty_repaint_count,
        COALESCE(p.reject_ppy_total, 0) AS reject_ppy_total,';

IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @DailyMetricToken, N''))) / LEN(@DailyMetricToken) <> 1
    THROW 52907, 'Dashboard DailyMetrics repaint marker is not unique.', 1;
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @DailyMetricToken, @DailyMetricReplacement);

DECLARE @PeriodMetricToken nvarchar(max) = N'        COALESCE(SUM(d.paint_fty_repaint_count), 0) AS paint_fty_repaint_count,
        COALESCE(SUM(d.reject_ppy_total), 0) AS reject_ppy_total,';
DECLARE @PeriodMetricReplacement nvarchar(max) = N'        COALESCE(SUM(d.paint_fty_repaint_count), 0) AS paint_fty_repaint_count,
        COALESCE(SUM(d.fuka_paint_fty_repaint_count), 0) AS fuka_paint_fty_repaint_count,
        COALESCE(SUM(d.bumper_paint_fty_repaint_count), 0) AS bumper_paint_fty_repaint_count,
        COALESCE(SUM(d.fairing_paint_fty_repaint_count), 0) AS fairing_paint_fty_repaint_count,
        COALESCE(SUM(d.reject_ppy_total), 0) AS reject_ppy_total,';

IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @PeriodMetricToken, N''))) / LEN(@PeriodMetricToken) <> 1
    THROW 52908, 'Dashboard PeriodMetrics repaint marker is not unique.', 1;
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @PeriodMetricToken, @PeriodMetricReplacement);

IF CHARINDEX(N'repaint_line_set', @CandidateDefinition) = 0
   OR CHARINDEX(N'fuka_paint_fty_repaint_count', @CandidateDefinition) = 0
   OR CHARINDEX(N'bumper_paint_fty_repaint_count', @CandidateDefinition) = 0
   OR CHARINDEX(N'fairing_paint_fty_repaint_count', @CandidateDefinition) = 0
    THROW 52909, 'Dashboard repaint line-set candidate is incomplete.', 1;

BEGIN TRANSACTION;
EXEC sys.sp_executesql @CandidateDefinition;

DECLARE @CandidateHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256',
    CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);

IF @ExpectedNewHash IS NOT NULL AND @CandidateHash <> @ExpectedNewHash
    THROW 52910, 'Dashboard repaint line-set candidate hash mismatch.', 1;

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
    THROW 52911, 'Dashboard repaint line-set final hash is inconsistent with commit mode.', 1;

SELECT
    Marker = N'ASTER_OPERATIONS_KPI_REPAINT_LINE_SET_V1',
    Applied = @CommitChange,
    OldDefinitionSHA256 = @ObservedOldHash,
    CandidateDefinitionSHA256 = @CandidateHash,
    FinalDefinitionSHA256 = @FinalHash;
