/*
    Replace history-derived paint outcomes with the metric-owner contract:

      - physical passes are linked by paint_oven_exited and dated by the
        authoritative oven-out timestamp;
      - Master Data Table preserves the first-pass EOL disposition;
      - load_line_repaint identifies repaint carts and RepaintCount controls
        their ordinal lineage;
      - the current EDI EOL disposition supplies the latest completed repaint
        outcome; an additional committed repaint proves the prior loop failed;
      - OEE/composite logic is deliberately untouched and is not an acceptance
        gate for this change.

    The current procedure hash is pinned. Preview with @CommitChange = 0 first,
    then pin @ExpectedNewHash and switch @CommitChange to 1 for deployment.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @ExpectedOldHash varchar(64) = 'A425832E9F652F84E55401DD45E917A8D421132442BBBA3EE37FD5136F4B26F5';
DECLARE @ExpectedNewHash varchar(64) = '87B95E7AF33FCAE6F9FD3C9BC0D5F76D3E270ACDB1115A4E5E7C1F407A9D3422';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @OldDefinition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedOldHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@OldDefinition, N''))), 2);

IF @ObservedOldHash <> @ExpectedOldHash
    THROW 52801, 'Dashboard Master/RepaintCount yield pre-change hash mismatch.', 1;

DECLARE @CandidateDefinition nvarchar(max) = @OldDefinition;
DECLARE @CreateHeader nvarchar(256) = N'CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @AlterHeader nvarchar(256) = N'ALTER   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';

IF CHARINDEX(@CreateHeader, @CandidateDefinition) > 0
    SET @CandidateDefinition = REPLACE(@CandidateDefinition, @CreateHeader, @AlterHeader);
ELSE IF CHARINDEX(@AlterHeader, @CandidateDefinition) = 0
    THROW 52802, 'Dashboard procedure header is not in the reviewed shape.', 1;

DECLARE @PhysicalStartToken nvarchar(200) = N'    /* Physical paint passes and the first EOL outcome after each pass. */';
DECLARE @PhysicalEndToken nvarchar(200) = N'    /* First receiving decision per part. */';
DECLARE @PhysicalStart int = CHARINDEX(@PhysicalStartToken, @CandidateDefinition);
DECLARE @PhysicalEnd int = CHARINDEX(@PhysicalEndToken, @CandidateDefinition, @PhysicalStart + 1);

IF @PhysicalStart = 0 OR @PhysicalEnd <= @PhysicalStart
    THROW 52803, 'Dashboard physical-pass block markers were not found.', 1;

DECLARE @NewPhysicalBlock nvarchar(max) = N'    /*
       Physical paint-pass contract.

       Item history links each part to a cart; tblCarts_Paint_Oven_Out supplies
       the authoritative pass timestamp. Master Data Table preserves the first
       EOL disposition. RepaintCount and load_line_repaint establish repaint
       ordinals without using mutable current disposition as first-pass truth.
    */
    SELECT
        m.ID AS part_id,
        NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), m.[Disposition EOL]))), N'''') AS first_disposition,
        COALESCE(m.RepaintCount, 0) AS repaint_count,
        CONVERT(datetime2(3), e.insp_line_end_stamp) AS current_eol_at,
        NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), e.insp_line_end_disposition))), N'''') AS current_disposition,
        pc.part_class
    INTO #YieldParts
    FROM dbo.[Master Data Table] AS m
    INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = m.ID
    INNER JOIN #PartClass AS pc ON pc.part_id = m.ID
    WHERE pc.is_paint_scope = 1;

    CREATE UNIQUE CLUSTERED INDEX IX_RollupYieldParts_Part ON #YieldParts(part_id);

    SELECT
        h.part_id,
        h.PaintCart_ID,
        CONVERT(datetime2(3), MIN(oo.TimeStamp_Out)) AS oven_out_at
    INTO #PhysicalPassLinks
    FROM #HistoryAll AS h
    INNER JOIN #YieldParts AS yp ON yp.part_id = h.part_id
    INNER JOIN dbo.tblCarts_Paint_Oven_Out AS oo ON oo.Cart_ID_Out = h.PaintCart_ID
    WHERE h.moment_category = N''paint_oven_exited''
      AND h.PaintCart_ID IS NOT NULL
      AND h.PaintCart_ID > 0
      AND oo.TimeStamp_Out >= CONVERT(datetime2(0), @HistoryStart)
      AND oo.TimeStamp_Out < @WindowEndExclusive
    GROUP BY h.part_id, h.PaintCart_ID;

    CREATE UNIQUE CLUSTERED INDEX IX_RollupPhysicalPass_PartCart ON #PhysicalPassLinks(part_id, PaintCart_ID);

    ;WITH RepaintCartEvents AS (
        SELECT
            h.part_id,
            h.PaintCart_ID,
            MIN(h.moment_at) AS loaded_at
        FROM #HistoryAll AS h
        INNER JOIN #YieldParts AS yp ON yp.part_id = h.part_id
        WHERE h.moment_category = N''load_line_repaint''
          AND h.PaintCart_ID IS NOT NULL
          AND h.PaintCart_ID > 0
        GROUP BY h.part_id, h.PaintCart_ID
    ), RankedRepaintLinks AS (
        SELECT
            r.part_id,
            r.PaintCart_ID,
            r.loaded_at,
            p.oven_out_at,
            ROW_NUMBER() OVER (
                PARTITION BY r.part_id
                ORDER BY r.loaded_at, r.PaintCart_ID
            ) AS loop_ordinal
        FROM RepaintCartEvents AS r
        INNER JOIN #PhysicalPassLinks AS p
            ON p.part_id = r.part_id
           AND p.PaintCart_ID = r.PaintCart_ID
        WHERE p.oven_out_at >= r.loaded_at
    )
    SELECT
        r.part_id,
        r.PaintCart_ID,
        r.oven_out_at,
        r.loop_ordinal
    INTO #RepaintPassLinks
    FROM RankedRepaintLinks AS r;

    CREATE UNIQUE CLUSTERED INDEX IX_RollupRepaintPass_PartCart ON #RepaintPassLinks(part_id, PaintCart_ID);

    ;WITH ClassifiedPasses AS (
        SELECT
            p.part_id,
            p.PaintCart_ID,
            p.oven_out_at,
            yp.part_class,
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
    SELECT
        part_id,
        PaintCart_ID,
        CONVERT(date, oven_out_at) AS event_date,
        oven_out_at AS event_at,
        part_class,
        is_initial_pass,
        is_repaint_loop,
        is_first_repaint_loop,
        CASE WHEN pass_disposition IN (N''Repaint'', N''Direct Repaint'') THEN 1 ELSE 0 END AS is_repaint_failure,
        CASE WHEN pass_disposition = N''Approved'' THEN 1 ELSE 0 END AS is_eol_approved,
        CASE WHEN pass_disposition IS NOT NULL AND pass_disposition <> N''Approved'' THEN 1 ELSE 0 END AS is_eol_reject,
        CASE WHEN pass_disposition IS NULL THEN 1 ELSE 0 END AS is_eol_pending
    INTO #PaintPasses
    FROM ClassifiedPasses;

    CREATE INDEX IX_RollupPaintDate ON #PaintPasses(event_date, part_id);

';

SET @CandidateDefinition = STUFF(
    @CandidateDefinition,
    @PhysicalStart,
    @PhysicalEnd - @PhysicalStart,
    @NewPhysicalBlock
);

DECLARE @PaintDailyStartToken nvarchar(100) = N'    ), PaintDaily AS (';
DECLARE @PaintDailyEndToken nvarchar(100) = N'    ), LoadedDaily AS (';
DECLARE @PaintDailyStart int = CHARINDEX(@PaintDailyStartToken, @CandidateDefinition);
DECLARE @PaintDailyEnd int = CHARINDEX(@PaintDailyEndToken, @CandidateDefinition, @PaintDailyStart + 1);

IF @PaintDailyStart = 0 OR @PaintDailyEnd <= @PaintDailyStart
    THROW 52804, 'Dashboard PaintDaily block markers were not found.', 1;

DECLARE @NewPaintDailyBlock nvarchar(max) = N'    ), PaintDaily AS (
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

IF CHARINDEX(N'Master Data Table', @CandidateDefinition) = 0
   OR CHARINDEX(N'RepaintCount', @CandidateDefinition) = 0
   OR CHARINDEX(N'is_repaint_failure', @CandidateDefinition) = 0
   OR CHARINDEX(N'tblCarts_Paint_Oven_Out', @CandidateDefinition) = 0
    THROW 52805, 'Dashboard Master/RepaintCount yield candidate is incomplete.', 1;

BEGIN TRANSACTION;
EXEC sys.sp_executesql @CandidateDefinition;

DECLARE @CandidateHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256',
    CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);

IF @ExpectedNewHash IS NOT NULL AND @CandidateHash <> @ExpectedNewHash
    THROW 52806, 'Dashboard Master/RepaintCount yield candidate hash mismatch.', 1;

IF @CommitChange = 1
    COMMIT TRANSACTION;
ELSE
    ROLLBACK TRANSACTION;

SELECT
    Marker = N'ASTER_OPERATIONS_KPI_MASTER_REPAINTCOUNT_YIELDS_V1',
    Applied = @CommitChange,
    OldDefinitionSHA256 = @ObservedOldHash,
    CandidateDefinitionSHA256 = @CandidateHash;
