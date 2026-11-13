/* Restore the exact v9 repaint/reject yield procedure definition. */
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @ExpectedOldHash varchar(64) = '87B95E7AF33FCAE6F9FD3C9BC0D5F76D3E270ACDB1115A4E5E7C1F407A9D3422';
DECLARE @ExpectedNewHash varchar(64) = 'A425832E9F652F84E55401DD45E917A8D421132442BBBA3EE37FD5136F4B26F5';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @OldDefinition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedOldHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@OldDefinition, N''))), 2);

IF @ObservedOldHash <> @ExpectedOldHash
    THROW 52901, 'Dashboard Master/RepaintCount rollback pre-change hash mismatch.', 1;

DECLARE @CandidateDefinition nvarchar(max) = @OldDefinition;
DECLARE @CreateHeader nvarchar(256) = N'CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @AlterHeader nvarchar(256) = N'ALTER   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';

IF CHARINDEX(@CreateHeader, @CandidateDefinition) > 0
    SET @CandidateDefinition = REPLACE(@CandidateDefinition, @CreateHeader, @AlterHeader);
ELSE IF CHARINDEX(@AlterHeader, @CandidateDefinition) = 0
    THROW 52902, 'Dashboard procedure header is not in the reviewed shape.', 1;

DECLARE @PhysicalStartToken nvarchar(200) = N'    /*
       Physical paint-pass contract.';
DECLARE @PhysicalEndToken nvarchar(200) = N'    /* First receiving decision per part. */';
DECLARE @PhysicalStart int = CHARINDEX(@PhysicalStartToken, @CandidateDefinition);
DECLARE @PhysicalEnd int = CHARINDEX(@PhysicalEndToken, @CandidateDefinition, @PhysicalStart + 1);

IF @PhysicalStart = 0 OR @PhysicalEnd <= @PhysicalStart
    THROW 52903, 'Dashboard v10 physical-pass block markers were not found.', 1;

DECLARE @RestoredPhysicalBlock nvarchar(max) = N'    /* Physical paint passes and the first EOL outcome after each pass. */
    WITH OvenOutEvents AS (
        SELECT
            h.id AS oven_out_history_id,
            h.part_id,
            h.PaintCart_ID,
            h.moment_at AS oven_out_at,
            ROW_NUMBER() OVER (
                PARTITION BY h.part_id, h.PaintCart_ID
                ORDER BY h.moment_at, h.id
            ) AS cart_event_rn
        FROM #HistoryAll AS h
        INNER JOIN #PartClass AS pc ON pc.part_id = h.part_id
        WHERE h.moment_category = N''paint_oven_exited''
          AND h.PaintCart_ID IS NOT NULL
          AND h.PaintCart_ID > 0
          AND pc.is_paint_scope = 1
    ), OvenOut AS (
        SELECT
            oven_out_history_id,
            part_id,
            PaintCart_ID,
            oven_out_at,
            ROW_NUMBER() OVER (
                PARTITION BY part_id
                ORDER BY oven_out_at, oven_out_history_id
            ) AS paint_pass_number
        FROM OvenOutEvents
        WHERE cart_event_rn = 1
    )
    SELECT
        o.part_id,
        CONVERT(date, o.oven_out_at) AS event_date,
        o.oven_out_at AS event_at,
        CASE WHEN o.paint_pass_number = 1 THEN 1 ELSE 0 END AS is_initial_pass,
        CASE WHEN o.paint_pass_number > 1 THEN 1 ELSE 0 END AS is_repaint_loop,
        CASE WHEN o.paint_pass_number = 2 THEN 1 ELSE 0 END AS is_first_repaint_loop,
        CASE
            WHEN q.quality_category IN (
                N''end_of_line_repair'', N''end_of_line_repaint'',
                N''end_of_line_direct_repaint'', N''end_of_line_reject''
            ) THEN 1 ELSE 0
        END AS is_eol_reject,
        CASE WHEN q.quality_category IS NULL THEN 1 ELSE 0 END AS is_eol_pending
    INTO #PaintPasses
    FROM OvenOut AS o
    OUTER APPLY (
        SELECT TOP (1)
            h.moment_category AS quality_category
        FROM #HistoryAll AS h
        WHERE h.part_id = o.part_id
          AND h.PaintCart_ID = o.PaintCart_ID
          AND h.id > o.oven_out_history_id
          AND h.moment_category IN (
              N''end_of_line_approved'', N''end_of_line_repair'', N''end_of_line_repaint'',
              N''end_of_line_direct_repaint'', N''end_of_line_reject''
          )
        ORDER BY h.id
    ) AS q;

    CREATE INDEX IX_RollupPaintDate ON #PaintPasses(event_date, part_id);

';

SET @CandidateDefinition = STUFF(
    @CandidateDefinition,
    @PhysicalStart,
    @PhysicalEnd - @PhysicalStart,
    @RestoredPhysicalBlock
);

DECLARE @PaintDailyStartToken nvarchar(100) = N'    ), PaintDaily AS (';
DECLARE @PaintDailyEndToken nvarchar(100) = N'    ), LoadedDaily AS (';
DECLARE @PaintDailyStart int = CHARINDEX(@PaintDailyStartToken, @CandidateDefinition);
DECLARE @PaintDailyEnd int = CHARINDEX(@PaintDailyEndToken, @CandidateDefinition, @PaintDailyStart + 1);

IF @PaintDailyStart = 0 OR @PaintDailyEnd <= @PaintDailyStart
    THROW 52904, 'Dashboard v10 PaintDaily block markers were not found.', 1;

DECLARE @RestoredPaintDailyBlock nvarchar(max) = N'    ), PaintDaily AS (
        SELECT
            p.event_date AS report_date,
            COUNT(*) AS paint_decision_pieces,
            SUM(CASE WHEN pc.part_class = N''Prd'' THEN 1 ELSE 0 END) AS production_paint_decision_pieces,
            SUM(CASE WHEN pc.part_class = N''BV'' THEN 1 ELSE 0 END) AS bv_paint_decision_pieces,
            SUM(CASE WHEN pc.part_class = N''Svc'' THEN 1 ELSE 0 END) AS service_paint_decision_pieces,
            SUM(p.is_initial_pass) AS ppy_approved,
            SUM(CASE WHEN pc.part_class = N''Prd'' THEN p.is_initial_pass ELSE 0 END) AS production_ppy_approved,
            SUM(CASE WHEN pc.part_class = N''BV'' THEN p.is_initial_pass ELSE 0 END) AS bv_ppy_approved,
            SUM(CASE WHEN pc.part_class = N''Svc'' THEN p.is_initial_pass ELSE 0 END) AS service_ppy_approved,
            SUM(p.is_repaint_loop) AS ppy_repaint_count,
            SUM(p.is_initial_pass) AS paint_fty_total,
            SUM(CASE WHEN pc.part_class = N''Prd'' THEN p.is_initial_pass ELSE 0 END) AS production_paint_fty_total,
            SUM(CASE WHEN pc.part_class = N''BV'' THEN p.is_initial_pass ELSE 0 END) AS bv_paint_fty_total,
            SUM(CASE WHEN pc.part_class = N''Svc'' THEN p.is_initial_pass ELSE 0 END) AS service_paint_fty_total,
            SUM(p.is_initial_pass) - SUM(p.is_first_repaint_loop) AS paint_fty_approved,
            SUM(CASE WHEN pc.part_class = N''Prd'' THEN p.is_initial_pass - p.is_first_repaint_loop ELSE 0 END) AS production_paint_fty_approved,
            SUM(CASE WHEN pc.part_class = N''BV'' THEN p.is_initial_pass - p.is_first_repaint_loop ELSE 0 END) AS bv_paint_fty_approved,
            SUM(CASE WHEN pc.part_class = N''Svc'' THEN p.is_initial_pass - p.is_first_repaint_loop ELSE 0 END) AS service_paint_fty_approved,
            SUM(p.is_first_repaint_loop) AS paint_fty_repaint_count,
            COUNT(*) AS reject_ppy_total,
            COUNT(*) - SUM(p.is_eol_reject) AS reject_ppy_approved,
            SUM(p.is_eol_reject) AS reject_ppy_rejected_count,
            SUM(p.is_eol_pending) AS reject_ppy_pending_count,
            SUM(p.is_initial_pass) AS reject_fty_total,
            SUM(p.is_initial_pass) - SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_eol_reject ELSE 0 END) AS reject_fty_approved,
            SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_eol_reject ELSE 0 END) AS reject_fty_rejected_count,
            SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_eol_pending ELSE 0 END) AS reject_fty_pending_count
        FROM #PaintPasses AS p
        INNER JOIN #PartClass AS pc ON pc.part_id = p.part_id
        GROUP BY p.event_date
';

SET @CandidateDefinition = STUFF(
    @CandidateDefinition,
    @PaintDailyStart,
    @PaintDailyEnd - @PaintDailyStart,
    @RestoredPaintDailyBlock
);

BEGIN TRANSACTION;
EXEC sys.sp_executesql @CandidateDefinition;

DECLARE @CandidateHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256',
    CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);

IF @CandidateHash <> @ExpectedNewHash
    THROW 52905, 'Dashboard Master/RepaintCount rollback hash mismatch.', 1;

IF @CommitChange = 1
    COMMIT TRANSACTION;
ELSE
    ROLLBACK TRANSACTION;

SELECT
    Marker = N'ASTER_OPERATIONS_KPI_MASTER_REPAINTCOUNT_YIELDS_ROLLBACK_V1',
    Applied = @CommitChange,
    OldDefinitionSHA256 = @ObservedOldHash,
    CandidateDefinitionSHA256 = @CandidateHash;
