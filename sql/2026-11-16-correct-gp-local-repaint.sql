/*
    Correct the repaint-yield contract for Brownsville-painted parts that are
    first painted at Grand Prairie after Receiving/Finesse routing.

    Master Data Table.Disposition EOL and RepaintCount are plant-agnostic.
    They remain the reviewed source for non-BV paint lineage, but they must not
    make a Brownsville outcome count as a Grand Prairie repaint failure.

    For BV parts only:
      - the first physical GP oven exit is the GP initial paint pass;
      - a later physical GP oven exit proves the preceding GP pass required a
        repaint;
      - the latest GP pass uses its same-cart EOL history outcome, falling back
        to current EDI only when that outcome occurred after the oven exit.

    Reject/Finesse outcome fields retain their existing contract. The new
    GP-local fields feed only Repaint PPY, Repaint FTY, Repaint %, their family
    split, and the inherited paint-plan quality component.

    Rollback-only forward and exact-reverse previews completed with
    @CommitChange = 0. The pinned candidate/reverse pair is now apply-ready.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @ExpectedOldHash varchar(64) = 'AC7DFDADC5C86C638385CD59265DA5E78A35C6A6A50F7CD869A014F7F02639BE';
DECLARE @ExpectedNewHash varchar(64) = '0B45A0737682B316113771E61A64F183EC04698FCEE48AF7F8B4CC94DABB7DC3';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @OldDefinition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedOldHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@OldDefinition, N''))), 2);

IF @ObservedOldHash <> @ExpectedOldHash
    THROW 53601, 'Dashboard GP-local repaint pre-change hash mismatch.', 1;

DECLARE @CandidateDefinition nvarchar(max) = @OldDefinition;
DECLARE @CreateHeader nvarchar(256) = N'CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @AlterHeader nvarchar(256) = N'ALTER   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';

IF CHARINDEX(@CreateHeader, @CandidateDefinition) > 0
    SET @CandidateDefinition = REPLACE(@CandidateDefinition, @CreateHeader, @AlterHeader);
ELSE IF CHARINDEX(@AlterHeader, @CandidateDefinition) = 0
    THROW 53602, 'Dashboard procedure header is not in the reviewed shape.', 1;

DECLARE @ClassifiedStartToken nvarchar(100) = N'    ;WITH ClassifiedPasses AS (';
DECLARE @PassSelectToken nvarchar(100) = N'    SELECT
        part_id,
        PaintCart_ID,';
DECLARE @ClassifiedStart int = CHARINDEX(@ClassifiedStartToken, @CandidateDefinition);
DECLARE @PassSelectStart int = CHARINDEX(@PassSelectToken, @CandidateDefinition, @ClassifiedStart + 1);

IF @ClassifiedStart = 0 OR @PassSelectStart <= @ClassifiedStart
    THROW 53603, 'Dashboard classified-pass block markers were not found.', 1;

DECLARE @NewClassifiedBlock nvarchar(max) = N'    ;WITH RankedPhysicalPasses AS (
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
';

SET @CandidateDefinition = STUFF(
    @CandidateDefinition,
    @ClassifiedStart,
    @PassSelectStart - @ClassifiedStart,
    @NewClassifiedBlock
);

DECLARE @PassFieldsToken nvarchar(max) = N'        is_first_repaint_loop,
        CASE WHEN pass_disposition IN (N''Repaint'', N''Direct Repaint'') THEN 1 ELSE 0 END AS is_repaint_failure,';
DECLARE @PassFieldsReplacement nvarchar(max) = N'        is_first_repaint_loop,
        repaint_is_initial_pass,
        repaint_is_failure,
        repaint_is_pending,
        CASE WHEN pass_disposition IN (N''Repaint'', N''Direct Repaint'') THEN 1 ELSE 0 END AS is_repaint_failure,';

IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @PassFieldsToken, N''))) / LEN(@PassFieldsToken) <> 1
    THROW 53604, 'Dashboard paint-pass output marker is not unique.', 1;
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @PassFieldsToken, @PassFieldsReplacement);

DECLARE @PaintDailyStartToken nvarchar(100) = N'    ), PaintDaily AS (';
DECLARE @PaintDailyEndToken nvarchar(100) = N'    ), LoadedDaily AS (';
DECLARE @PaintDailyStart int = CHARINDEX(@PaintDailyStartToken, @CandidateDefinition);
DECLARE @PaintDailyEnd int = CHARINDEX(@PaintDailyEndToken, @CandidateDefinition, @PaintDailyStart + 1);

IF @PaintDailyStart = 0 OR @PaintDailyEnd <= @PaintDailyStart
    THROW 53605, 'Dashboard PaintDaily block markers were not found.', 1;

DECLARE @NewPaintDailyBlock nvarchar(max) = N'    ), PaintDaily AS (
        SELECT
            p.event_date AS report_date,
            COUNT(*) AS paint_decision_pieces,
            SUM(CASE WHEN p.part_class = N''Prd'' THEN 1 ELSE 0 END) AS production_paint_decision_pieces,
            SUM(CASE WHEN p.part_class = N''BV'' THEN 1 ELSE 0 END) AS bv_paint_decision_pieces,
            SUM(CASE WHEN p.part_class = N''Svc'' THEN 1 ELSE 0 END) AS service_paint_decision_pieces,
            SUM(CASE WHEN p.repaint_is_pending = 0 AND p.repaint_is_failure = 0 THEN 1 ELSE 0 END) AS ppy_approved,
            SUM(CASE WHEN p.part_class = N''Prd'' AND p.repaint_is_pending = 0 AND p.repaint_is_failure = 0 THEN 1 ELSE 0 END) AS production_ppy_approved,
            SUM(CASE WHEN p.part_class = N''BV'' AND p.repaint_is_pending = 0 AND p.repaint_is_failure = 0 THEN 1 ELSE 0 END) AS bv_ppy_approved,
            SUM(CASE WHEN p.part_class = N''Svc'' AND p.repaint_is_pending = 0 AND p.repaint_is_failure = 0 THEN 1 ELSE 0 END) AS service_ppy_approved,
            SUM(p.repaint_is_failure) AS ppy_repaint_count,
            SUM(p.repaint_is_pending) AS repaint_ppy_pending_count,
            SUM(p.repaint_is_initial_pass) AS paint_fty_total,
            SUM(CASE WHEN p.part_class = N''Prd'' THEN p.repaint_is_initial_pass ELSE 0 END) AS production_paint_fty_total,
            SUM(CASE WHEN p.part_class = N''BV'' THEN p.repaint_is_initial_pass ELSE 0 END) AS bv_paint_fty_total,
            SUM(CASE WHEN p.part_class = N''Svc'' THEN p.repaint_is_initial_pass ELSE 0 END) AS service_paint_fty_total,
            SUM(CASE WHEN p.repaint_is_initial_pass = 1 AND p.repaint_is_pending = 0 AND p.repaint_is_failure = 0 THEN 1 ELSE 0 END) AS paint_fty_approved,
            SUM(CASE WHEN p.part_class = N''Prd'' AND p.repaint_is_initial_pass = 1 AND p.repaint_is_pending = 0 AND p.repaint_is_failure = 0 THEN 1 ELSE 0 END) AS production_paint_fty_approved,
            SUM(CASE WHEN p.part_class = N''BV'' AND p.repaint_is_initial_pass = 1 AND p.repaint_is_pending = 0 AND p.repaint_is_failure = 0 THEN 1 ELSE 0 END) AS bv_paint_fty_approved,
            SUM(CASE WHEN p.part_class = N''Svc'' AND p.repaint_is_initial_pass = 1 AND p.repaint_is_pending = 0 AND p.repaint_is_failure = 0 THEN 1 ELSE 0 END) AS service_paint_fty_approved,
            SUM(CASE WHEN p.repaint_is_initial_pass = 1 THEN p.repaint_is_failure ELSE 0 END) AS paint_fty_repaint_count,
            SUM(CASE WHEN p.repaint_is_initial_pass = 1 THEN p.repaint_is_pending ELSE 0 END) AS repaint_fty_pending_count,
            SUM(CASE WHEN p.repaint_is_initial_pass = 1 AND p.repaint_is_failure = 1 AND p.repaint_line_set = N''FUKA'' THEN 1 ELSE 0 END) AS fuka_paint_fty_repaint_count,
            SUM(CASE WHEN p.repaint_is_initial_pass = 1 AND p.repaint_is_failure = 1 AND p.repaint_line_set = N''Bumpers'' THEN 1 ELSE 0 END) AS bumper_paint_fty_repaint_count,
            SUM(CASE WHEN p.repaint_is_initial_pass = 1 AND p.repaint_is_failure = 1 AND p.repaint_line_set = N''Fairings'' THEN 1 ELSE 0 END) AS fairing_paint_fty_repaint_count,
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

SET @CandidateDefinition = STUFF(
    @CandidateDefinition,
    @PaintDailyStart,
    @PaintDailyEnd - @PaintDailyStart,
    @NewPaintDailyBlock
);

DECLARE @DailyPpyToken nvarchar(max) = N'        COALESCE(p.ppy_repaint_count, 0) AS ppy_repaint_count,
        COALESCE(p.paint_fty_total, 0) AS paint_fty_total,';
DECLARE @DailyPpyReplacement nvarchar(max) = N'        COALESCE(p.ppy_repaint_count, 0) AS ppy_repaint_count,
        COALESCE(p.repaint_ppy_pending_count, 0) AS repaint_ppy_pending_count,
        COALESCE(p.paint_fty_total, 0) AS paint_fty_total,';
DECLARE @DailyFtyToken nvarchar(max) = N'        COALESCE(p.paint_fty_repaint_count, 0) AS paint_fty_repaint_count,
        COALESCE(p.fuka_paint_fty_repaint_count, 0) AS fuka_paint_fty_repaint_count,';
DECLARE @DailyFtyReplacement nvarchar(max) = N'        COALESCE(p.paint_fty_repaint_count, 0) AS paint_fty_repaint_count,
        COALESCE(p.repaint_fty_pending_count, 0) AS repaint_fty_pending_count,
        COALESCE(p.fuka_paint_fty_repaint_count, 0) AS fuka_paint_fty_repaint_count,';
DECLARE @PeriodPpyToken nvarchar(max) = N'        COALESCE(SUM(d.ppy_repaint_count), 0) AS ppy_repaint_count,
        COALESCE(SUM(d.paint_fty_total), 0) AS paint_fty_total,';
DECLARE @PeriodPpyReplacement nvarchar(max) = N'        COALESCE(SUM(d.ppy_repaint_count), 0) AS ppy_repaint_count,
        COALESCE(SUM(d.repaint_ppy_pending_count), 0) AS repaint_ppy_pending_count,
        COALESCE(SUM(d.paint_fty_total), 0) AS paint_fty_total,';
DECLARE @PeriodFtyToken nvarchar(max) = N'        COALESCE(SUM(d.paint_fty_repaint_count), 0) AS paint_fty_repaint_count,
        COALESCE(SUM(d.fuka_paint_fty_repaint_count), 0) AS fuka_paint_fty_repaint_count,';
DECLARE @PeriodFtyReplacement nvarchar(max) = N'        COALESCE(SUM(d.paint_fty_repaint_count), 0) AS paint_fty_repaint_count,
        COALESCE(SUM(d.repaint_fty_pending_count), 0) AS repaint_fty_pending_count,
        COALESCE(SUM(d.fuka_paint_fty_repaint_count), 0) AS fuka_paint_fty_repaint_count,';

IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @DailyPpyToken, N''))) / LEN(@DailyPpyToken) <> 1
   OR (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @DailyFtyToken, N''))) / LEN(@DailyFtyToken) <> 1
   OR (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @PeriodPpyToken, N''))) / LEN(@PeriodPpyToken) <> 1
   OR (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @PeriodFtyToken, N''))) / LEN(@PeriodFtyToken) <> 1
    THROW 53606, 'Dashboard repaint pending-field marker count mismatch.', 1;

SET @CandidateDefinition = REPLACE(@CandidateDefinition, @DailyPpyToken, @DailyPpyReplacement);
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @DailyFtyToken, @DailyFtyReplacement);
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @PeriodPpyToken, @PeriodPpyReplacement);
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @PeriodFtyToken, @PeriodFtyReplacement);

IF CHARINDEX(N'RepaintCount', @CandidateDefinition) = 0
   OR CHARINDEX(N'repaint_is_initial_pass', @CandidateDefinition) = 0
   OR CHARINDEX(N'repaint_is_failure', @CandidateDefinition) = 0
   OR CHARINDEX(N'repaint_is_pending', @CandidateDefinition) = 0
   OR CHARINDEX(N'gp_pass_ordinal', @CandidateDefinition) = 0
   OR CHARINDEX(N'repaint_ppy_pending_count', @CandidateDefinition) = 0
   OR CHARINDEX(N'repaint_fty_pending_count', @CandidateDefinition) = 0
    THROW 53607, 'Dashboard GP-local repaint candidate is incomplete.', 1;

BEGIN TRANSACTION;
EXEC sys.sp_executesql @CandidateDefinition;

DECLARE @CandidateHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256',
    CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);

IF @ExpectedNewHash IS NOT NULL AND @CandidateHash <> @ExpectedNewHash
    THROW 53608, 'Dashboard GP-local repaint candidate hash mismatch.', 1;

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
    THROW 53609, 'Dashboard GP-local repaint final hash is inconsistent with commit mode.', 1;

SELECT
    Marker = N'ASTER_OPERATIONS_KPI_GP_LOCAL_REPAINT_V1',
    Applied = @CommitChange,
    OldDefinitionSHA256 = @ObservedOldHash,
    CandidateDefinitionSHA256 = @CandidateHash,
    FinalDefinitionSHA256 = @FinalHash;
