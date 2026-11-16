/* Exact reverse of 2026-11-16-correct-gp-local-repaint.sql. */
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @ExpectedOldHash varchar(64) = '0B45A0737682B316113771E61A64F183EC04698FCEE48AF7F8B4CC94DABB7DC3';
DECLARE @ExpectedNewHash varchar(64) = 'AC7DFDADC5C86C638385CD59265DA5E78A35C6A6A50F7CD869A014F7F02639BE';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @OldDefinition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedOldHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@OldDefinition, N''))), 2);

IF @ObservedOldHash <> @ExpectedOldHash
    THROW 53621, 'Dashboard GP-local repaint rollback pre-change hash mismatch.', 1;

DECLARE @RollbackDefinition nvarchar(max) = @OldDefinition;
DECLARE @CreateHeader nvarchar(256) = N'CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @AlterHeader nvarchar(256) = N'ALTER   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';

IF CHARINDEX(@CreateHeader, @RollbackDefinition) > 0
    SET @RollbackDefinition = REPLACE(@RollbackDefinition, @CreateHeader, @AlterHeader);
ELSE IF CHARINDEX(@AlterHeader, @RollbackDefinition) = 0
    THROW 53622, 'Dashboard rollback procedure header is not in the reviewed shape.', 1;

DECLARE @ClassifiedStartToken nvarchar(100) = N'    ;WITH RankedPhysicalPasses AS (';
DECLARE @PassSelectToken nvarchar(100) = N'    SELECT
        part_id,
        PaintCart_ID,';
DECLARE @ClassifiedStart int = CHARINDEX(@ClassifiedStartToken, @RollbackDefinition);
DECLARE @PassSelectStart int = CHARINDEX(@PassSelectToken, @RollbackDefinition, @ClassifiedStart + 1);

IF @ClassifiedStart = 0 OR @PassSelectStart <= @ClassifiedStart
    THROW 53623, 'Dashboard rollback classified-pass block markers were not found.', 1;

DECLARE @OriginalClassifiedBlock nvarchar(max) = N'    ;WITH ClassifiedPasses AS (
        SELECT
            p.part_id,
            p.PaintCart_ID,
            p.oven_out_at,
            yp.part_class,
            yp.repaint_line_set,
            CASE WHEN r.part_id IS NULL THEN 1 ELSE 0 END AS is_initial_pass,
            CASE WHEN r.part_id IS NULL THEN 0 ELSE 1 END AS is_repaint_loop,
            CASE WHEN r.loop_ordinal = 1 THEN 1 ELSE 0 END AS is_first_repaint_loop,
            CASE
                WHEN r.part_id IS NULL THEN yp.first_disposition
                WHEN r.loop_ordinal < yp.repaint_count THEN N''Repaint''
                WHEN r.loop_ordinal = yp.repaint_count AND yp.current_eol_at >= p.oven_out_at THEN yp.current_disposition
                ELSE NULL
            END AS pass_disposition
        FROM #PhysicalPassLinks AS p
        INNER JOIN #YieldParts AS yp ON yp.part_id = p.part_id
        LEFT JOIN #RepaintPassLinks AS r
            ON r.part_id = p.part_id
           AND r.PaintCart_ID = p.PaintCart_ID
    )
';

SET @RollbackDefinition = STUFF(
    @RollbackDefinition,
    @ClassifiedStart,
    @PassSelectStart - @ClassifiedStart,
    @OriginalClassifiedBlock
);

DECLARE @PassFieldsToken nvarchar(max) = N'        is_first_repaint_loop,
        repaint_is_initial_pass,
        repaint_is_failure,
        repaint_is_pending,
        CASE WHEN pass_disposition IN (N''Repaint'', N''Direct Repaint'') THEN 1 ELSE 0 END AS is_repaint_failure,';
DECLARE @PassFieldsReplacement nvarchar(max) = N'        is_first_repaint_loop,
        CASE WHEN pass_disposition IN (N''Repaint'', N''Direct Repaint'') THEN 1 ELSE 0 END AS is_repaint_failure,';

IF (LEN(@RollbackDefinition) - LEN(REPLACE(@RollbackDefinition, @PassFieldsToken, N''))) / LEN(@PassFieldsToken) <> 1
    THROW 53624, 'Dashboard rollback paint-pass output marker is not unique.', 1;
SET @RollbackDefinition = REPLACE(@RollbackDefinition, @PassFieldsToken, @PassFieldsReplacement);

DECLARE @PaintDailyStartToken nvarchar(100) = N'    ), PaintDaily AS (';
DECLARE @PaintDailyEndToken nvarchar(100) = N'    ), LoadedDaily AS (';
DECLARE @PaintDailyStart int = CHARINDEX(@PaintDailyStartToken, @RollbackDefinition);
DECLARE @PaintDailyEnd int = CHARINDEX(@PaintDailyEndToken, @RollbackDefinition, @PaintDailyStart + 1);

IF @PaintDailyStart = 0 OR @PaintDailyEnd <= @PaintDailyStart
    THROW 53625, 'Dashboard rollback PaintDaily block markers were not found.', 1;

DECLARE @OriginalPaintDailyBlock nvarchar(max) = N'    ), PaintDaily AS (
        SELECT
            p.event_date AS report_date,
            COUNT(*) AS paint_decision_pieces,
            SUM(CASE WHEN p.part_class = N''Prd'' THEN 1 ELSE 0 END) AS production_paint_decision_pieces,
            SUM(CASE WHEN p.part_class = N''BV'' THEN 1 ELSE 0 END) AS bv_paint_decision_pieces,
            SUM(CASE WHEN p.part_class = N''Svc'' THEN 1 ELSE 0 END) AS service_paint_decision_pieces,
            SUM(CASE WHEN p.is_eol_pending = 0 AND p.is_repaint_failure = 0 THEN 1 ELSE 0 END) AS ppy_approved,
            SUM(CASE WHEN p.part_class = N''Prd'' AND p.is_eol_pending = 0 AND p.is_repaint_failure = 0 THEN 1 ELSE 0 END) AS production_ppy_approved,
            SUM(CASE WHEN p.part_class = N''BV'' AND p.is_eol_pending = 0 AND p.is_repaint_failure = 0 THEN 1 ELSE 0 END) AS bv_ppy_approved,
            SUM(CASE WHEN p.part_class = N''Svc'' AND p.is_eol_pending = 0 AND p.is_repaint_failure = 0 THEN 1 ELSE 0 END) AS service_ppy_approved,
            SUM(p.is_repaint_failure) AS ppy_repaint_count,
            SUM(p.is_initial_pass) AS paint_fty_total,
            SUM(CASE WHEN p.part_class = N''Prd'' THEN p.is_initial_pass ELSE 0 END) AS production_paint_fty_total,
            SUM(CASE WHEN p.part_class = N''BV'' THEN p.is_initial_pass ELSE 0 END) AS bv_paint_fty_total,
            SUM(CASE WHEN p.part_class = N''Svc'' THEN p.is_initial_pass ELSE 0 END) AS service_paint_fty_total,
            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_eol_pending = 0 AND p.is_repaint_failure = 0 THEN 1 ELSE 0 END) AS paint_fty_approved,
            SUM(CASE WHEN p.part_class = N''Prd'' AND p.is_initial_pass = 1 AND p.is_eol_pending = 0 AND p.is_repaint_failure = 0 THEN 1 ELSE 0 END) AS production_paint_fty_approved,
            SUM(CASE WHEN p.part_class = N''BV'' AND p.is_initial_pass = 1 AND p.is_eol_pending = 0 AND p.is_repaint_failure = 0 THEN 1 ELSE 0 END) AS bv_paint_fty_approved,
            SUM(CASE WHEN p.part_class = N''Svc'' AND p.is_initial_pass = 1 AND p.is_eol_pending = 0 AND p.is_repaint_failure = 0 THEN 1 ELSE 0 END) AS service_paint_fty_approved,
            SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_repaint_failure ELSE 0 END) AS paint_fty_repaint_count,
            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_repaint_failure = 1 AND p.repaint_line_set = N''FUKA'' THEN 1 ELSE 0 END) AS fuka_paint_fty_repaint_count,
            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_repaint_failure = 1 AND p.repaint_line_set = N''Bumpers'' THEN 1 ELSE 0 END) AS bumper_paint_fty_repaint_count,
            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_repaint_failure = 1 AND p.repaint_line_set = N''Fairings'' THEN 1 ELSE 0 END) AS fairing_paint_fty_repaint_count,
            SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_finesse_repair ELSE 0 END) AS paint_fty_repair_count,
            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_finesse_repair = 1 AND p.repaint_line_set = N''FUKA'' THEN 1 ELSE 0 END) AS fuka_paint_fty_repair_count,
            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_finesse_repair = 1 AND p.repaint_line_set = N''Fairings'' THEN 1 ELSE 0 END) AS fairing_paint_fty_repair_count,
            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_finesse_repair = 1 AND p.repaint_line_set = N''Bumpers'' THEN 1 ELSE 0 END) AS bumper_paint_fty_repair_count,
            COUNT(*) AS reject_ppy_total,
            SUM(p.is_eol_approved) AS reject_ppy_approved,
            SUM(p.is_eol_reject) AS reject_ppy_rejected_count,
            SUM(p.is_eol_pending) AS reject_ppy_pending_count,
            SUM(p.is_initial_pass) AS reject_fty_total,
            SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_eol_approved ELSE 0 END) AS reject_fty_approved,
            SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_eol_reject ELSE 0 END) AS reject_fty_rejected_count,
            SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_eol_pending ELSE 0 END) AS reject_fty_pending_count
        FROM #PaintPasses AS p
        GROUP BY p.event_date
';

SET @RollbackDefinition = STUFF(
    @RollbackDefinition,
    @PaintDailyStart,
    @PaintDailyEnd - @PaintDailyStart,
    @OriginalPaintDailyBlock
);

DECLARE @DailyPpyToken nvarchar(max) = N'        COALESCE(p.ppy_repaint_count, 0) AS ppy_repaint_count,
        COALESCE(p.repaint_ppy_pending_count, 0) AS repaint_ppy_pending_count,
        COALESCE(p.paint_fty_total, 0) AS paint_fty_total,';
DECLARE @DailyPpyReplacement nvarchar(max) = N'        COALESCE(p.ppy_repaint_count, 0) AS ppy_repaint_count,
        COALESCE(p.paint_fty_total, 0) AS paint_fty_total,';
DECLARE @DailyFtyToken nvarchar(max) = N'        COALESCE(p.paint_fty_repaint_count, 0) AS paint_fty_repaint_count,
        COALESCE(p.repaint_fty_pending_count, 0) AS repaint_fty_pending_count,
        COALESCE(p.fuka_paint_fty_repaint_count, 0) AS fuka_paint_fty_repaint_count,';
DECLARE @DailyFtyReplacement nvarchar(max) = N'        COALESCE(p.paint_fty_repaint_count, 0) AS paint_fty_repaint_count,
        COALESCE(p.fuka_paint_fty_repaint_count, 0) AS fuka_paint_fty_repaint_count,';
DECLARE @PeriodPpyToken nvarchar(max) = N'        COALESCE(SUM(d.ppy_repaint_count), 0) AS ppy_repaint_count,
        COALESCE(SUM(d.repaint_ppy_pending_count), 0) AS repaint_ppy_pending_count,
        COALESCE(SUM(d.paint_fty_total), 0) AS paint_fty_total,';
DECLARE @PeriodPpyReplacement nvarchar(max) = N'        COALESCE(SUM(d.ppy_repaint_count), 0) AS ppy_repaint_count,
        COALESCE(SUM(d.paint_fty_total), 0) AS paint_fty_total,';
DECLARE @PeriodFtyToken nvarchar(max) = N'        COALESCE(SUM(d.paint_fty_repaint_count), 0) AS paint_fty_repaint_count,
        COALESCE(SUM(d.repaint_fty_pending_count), 0) AS repaint_fty_pending_count,
        COALESCE(SUM(d.fuka_paint_fty_repaint_count), 0) AS fuka_paint_fty_repaint_count,';
DECLARE @PeriodFtyReplacement nvarchar(max) = N'        COALESCE(SUM(d.paint_fty_repaint_count), 0) AS paint_fty_repaint_count,
        COALESCE(SUM(d.fuka_paint_fty_repaint_count), 0) AS fuka_paint_fty_repaint_count,';

IF (LEN(@RollbackDefinition) - LEN(REPLACE(@RollbackDefinition, @DailyPpyToken, N''))) / LEN(@DailyPpyToken) <> 1
   OR (LEN(@RollbackDefinition) - LEN(REPLACE(@RollbackDefinition, @DailyFtyToken, N''))) / LEN(@DailyFtyToken) <> 1
   OR (LEN(@RollbackDefinition) - LEN(REPLACE(@RollbackDefinition, @PeriodPpyToken, N''))) / LEN(@PeriodPpyToken) <> 1
   OR (LEN(@RollbackDefinition) - LEN(REPLACE(@RollbackDefinition, @PeriodFtyToken, N''))) / LEN(@PeriodFtyToken) <> 1
    THROW 53626, 'Dashboard rollback repaint pending-field marker count mismatch.', 1;

SET @RollbackDefinition = REPLACE(@RollbackDefinition, @DailyPpyToken, @DailyPpyReplacement);
SET @RollbackDefinition = REPLACE(@RollbackDefinition, @DailyFtyToken, @DailyFtyReplacement);
SET @RollbackDefinition = REPLACE(@RollbackDefinition, @PeriodPpyToken, @PeriodPpyReplacement);
SET @RollbackDefinition = REPLACE(@RollbackDefinition, @PeriodFtyToken, @PeriodFtyReplacement);

IF CHARINDEX(N'repaint_is_initial_pass', @RollbackDefinition) > 0
   OR CHARINDEX(N'repaint_is_failure', @RollbackDefinition) > 0
   OR CHARINDEX(N'repaint_is_pending', @RollbackDefinition) > 0
   OR CHARINDEX(N'gp_pass_ordinal', @RollbackDefinition) > 0
   OR CHARINDEX(N'repaint_ppy_pending_count', @RollbackDefinition) > 0
   OR CHARINDEX(N'repaint_fty_pending_count', @RollbackDefinition) > 0
    THROW 53627, 'Dashboard GP-local repaint rollback left candidate markers behind.', 1;

BEGIN TRANSACTION;
EXEC sys.sp_executesql @RollbackDefinition;

DECLARE @RollbackHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256',
    CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);

IF @RollbackHash <> @ExpectedNewHash
    THROW 53628, 'Dashboard GP-local repaint rollback hash mismatch.', 1;

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
    THROW 53629, 'Dashboard GP-local repaint rollback final hash is inconsistent with commit mode.', 1;

SELECT
    Marker = N'ASTER_OPERATIONS_KPI_GP_LOCAL_REPAINT_ROLLBACK_V1',
    Applied = @CommitChange,
    OldDefinitionSHA256 = @ObservedOldHash,
    RollbackDefinitionSHA256 = @RollbackHash,
    FinalDefinitionSHA256 = @FinalHash;
