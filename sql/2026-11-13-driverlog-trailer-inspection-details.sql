/*
    Reversible aggregate-only Operations KPI contract change.

    Forward mode adds:
      - DriverLog TimeOut trailer departures by report date;
      - Receiving first-decision Bumpers/Fairings totals and approvals;
      - Final first-decision FUKA/Bumpers/Fairings totals and approvals;
      - First-pass Repair counts for the Finesse rejected-outcome share;
      - Paint Prep staged cart-group/piece totals from the owner-approved queue.

    Rollback mode removes exactly those fields and restores the reviewed
    pre-change procedure hash. No driver names, trailer IDs, destinations,
    notes, part IDs, or other row-level values leave the procedure.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @RollbackChange bit = 0;
DECLARE @BaseHash varchar(64) = '415953E2A0675AADA2C99A7BABC4F43DBB04B21ACB7BB8D9361AF094C96B7CE3';
DECLARE @DetailHash varchar(64) = '21149FDE5DB32871914F9846F6E29FCF7D071BC6189D7A2272E9E7E4FC0C2DF3';
DECLARE @ExpectedOldHash varchar(64) = CASE WHEN @RollbackChange = 1 THEN @DetailHash ELSE @BaseHash END;
DECLARE @ExpectedNewHash varchar(64) = CASE WHEN @RollbackChange = 1 THEN @BaseHash ELSE @DetailHash END;
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @OldDefinition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedOldHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@OldDefinition, N''))), 2);

IF @ObservedOldHash <> @ExpectedOldHash
    THROW 53301, 'Dashboard trailer/inspection-detail pre-change hash mismatch.', 1;

DECLARE @CandidateDefinition nvarchar(max) = @OldDefinition;
DECLARE @CreateHeader nvarchar(256) = N'CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @AlterHeader nvarchar(256) = N'ALTER   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';

IF CHARINDEX(@CreateHeader, @CandidateDefinition) > 0
    SET @CandidateDefinition = REPLACE(@CandidateDefinition, @CreateHeader, @AlterHeader);
ELSE IF CHARINDEX(@AlterHeader, @CandidateDefinition) = 0
    THROW 53302, 'Dashboard procedure header is not in the reviewed shape.', 1;

DECLARE @OldReceiving nvarchar(max) = N'    /* First receiving decision per part. */
    WITH FirstReceiving AS (
        SELECT
            h.part_id,
            h.moment_date,
            h.moment_category,
            ROW_NUMBER() OVER (PARTITION BY h.part_id ORDER BY h.moment_at, h.id) AS rn
        FROM #History AS h
        WHERE h.moment_category IN (N''receiving_approved'', N''receiving_reject'')
    )
    SELECT
        moment_date AS event_date,
        COUNT(*) AS receiving_total,
        SUM(CASE WHEN moment_category = N''receiving_approved'' THEN 1 ELSE 0 END) AS receiving_approved
    INTO #ReceivingFirst
    FROM FirstReceiving
    WHERE rn = 1
    GROUP BY moment_date;';
DECLARE @NewReceiving nvarchar(max) = N'    /* First receiving decision per part, split by requested product family. */
    WITH FirstReceiving AS (
        SELECT
            h.part_id,
            h.moment_date,
            h.moment_category,
            CASE
                WHEN CONVERT(nvarchar(10), e.Origin) = N''B'' THEN N''Bumpers''
                WHEN CONVERT(nvarchar(10), e.Origin) = N''F''
                 AND (LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71%''
                   OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N33%'') THEN N''Fairings''
                ELSE N''FUKA''
            END AS inspection_line_set,
            ROW_NUMBER() OVER (PARTITION BY h.part_id ORDER BY h.moment_at, h.id) AS rn
        FROM #History AS h
        INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = h.part_id
        WHERE h.moment_category IN (N''receiving_approved'', N''receiving_reject'')
    )
    SELECT
        moment_date AS event_date,
        COUNT(*) AS receiving_total,
        SUM(CASE WHEN moment_category = N''receiving_approved'' THEN 1 ELSE 0 END) AS receiving_approved,
        SUM(CASE WHEN inspection_line_set = N''Bumpers'' THEN 1 ELSE 0 END) AS receiving_bumper_total,
        SUM(CASE WHEN inspection_line_set = N''Bumpers'' AND moment_category = N''receiving_approved'' THEN 1 ELSE 0 END) AS receiving_bumper_approved,
        SUM(CASE WHEN inspection_line_set = N''Fairings'' THEN 1 ELSE 0 END) AS receiving_fairing_total,
        SUM(CASE WHEN inspection_line_set = N''Fairings'' AND moment_category = N''receiving_approved'' THEN 1 ELSE 0 END) AS receiving_fairing_approved
    INTO #ReceivingFirst
    FROM FirstReceiving
    WHERE rn = 1
    GROUP BY moment_date;';

DECLARE @OldFinal nvarchar(max) = N'    /* First final-inspection decision per part. */
    WITH FirstFinal AS (
        SELECT
            h.part_id,
            h.moment_date,
            h.moment_category,
            ROW_NUMBER() OVER (PARTITION BY h.part_id ORDER BY h.moment_at, h.id) AS rn
        FROM #History AS h
        WHERE h.moment_category IN (N''final_approved'', N''final_reject'')
    )
    SELECT
        moment_date AS event_date,
        COUNT(*) AS final_total,
        SUM(CASE WHEN moment_category = N''final_approved'' THEN 1 ELSE 0 END) AS final_approved
    INTO #FinalFirst
    FROM FirstFinal
    WHERE rn = 1
    GROUP BY moment_date;';
DECLARE @NewFinal nvarchar(max) = N'    /* First final-inspection decision per part, split by product family. */
    WITH FirstFinal AS (
        SELECT
            h.part_id,
            h.moment_date,
            h.moment_category,
            CASE
                WHEN CONVERT(nvarchar(10), e.Origin) = N''B'' THEN N''Bumpers''
                WHEN CONVERT(nvarchar(10), e.Origin) = N''F''
                 AND (LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71%''
                   OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N33%'') THEN N''Fairings''
                ELSE N''FUKA''
            END AS inspection_line_set,
            ROW_NUMBER() OVER (PARTITION BY h.part_id ORDER BY h.moment_at, h.id) AS rn
        FROM #History AS h
        INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = h.part_id
        WHERE h.moment_category IN (N''final_approved'', N''final_reject'')
    )
    SELECT
        moment_date AS event_date,
        COUNT(*) AS final_total,
        SUM(CASE WHEN moment_category = N''final_approved'' THEN 1 ELSE 0 END) AS final_approved,
        SUM(CASE WHEN inspection_line_set = N''FUKA'' THEN 1 ELSE 0 END) AS final_fuka_total,
        SUM(CASE WHEN inspection_line_set = N''FUKA'' AND moment_category = N''final_approved'' THEN 1 ELSE 0 END) AS final_fuka_approved,
        SUM(CASE WHEN inspection_line_set = N''Bumpers'' THEN 1 ELSE 0 END) AS final_bumper_total,
        SUM(CASE WHEN inspection_line_set = N''Bumpers'' AND moment_category = N''final_approved'' THEN 1 ELSE 0 END) AS final_bumper_approved,
        SUM(CASE WHEN inspection_line_set = N''Fairings'' THEN 1 ELSE 0 END) AS final_fairing_total,
        SUM(CASE WHEN inspection_line_set = N''Fairings'' AND moment_category = N''final_approved'' THEN 1 ELSE 0 END) AS final_fairing_approved
    INTO #FinalFirst
    FROM FirstFinal
    WHERE rn = 1
    GROUP BY moment_date;';

DECLARE @OldDailyInspection nvarchar(max) = N'        COALESCE(r.receiving_total, 0) AS receiving_total,
        COALESCE(r.receiving_approved, 0) AS receiving_approved,
        COALESCE(rq.receiving_quantity, 0) AS receiving_quantity,
        COALESCE(f.final_total, 0) AS final_total,
        COALESCE(f.final_approved, 0) AS final_approved,
        COALESCE(fq.final_quantity, 0) AS final_quantity,';
DECLARE @NewDailyInspection nvarchar(max) = N'        COALESCE(r.receiving_total, 0) AS receiving_total,
        COALESCE(r.receiving_approved, 0) AS receiving_approved,
        COALESCE(r.receiving_bumper_total, 0) AS receiving_bumper_total,
        COALESCE(r.receiving_bumper_approved, 0) AS receiving_bumper_approved,
        COALESCE(r.receiving_fairing_total, 0) AS receiving_fairing_total,
        COALESCE(r.receiving_fairing_approved, 0) AS receiving_fairing_approved,
        COALESCE(rq.receiving_quantity, 0) AS receiving_quantity,
        COALESCE(f.final_total, 0) AS final_total,
        COALESCE(f.final_approved, 0) AS final_approved,
        COALESCE(f.final_fuka_total, 0) AS final_fuka_total,
        COALESCE(f.final_fuka_approved, 0) AS final_fuka_approved,
        COALESCE(f.final_bumper_total, 0) AS final_bumper_total,
        COALESCE(f.final_bumper_approved, 0) AS final_bumper_approved,
        COALESCE(f.final_fairing_total, 0) AS final_fairing_total,
        COALESCE(f.final_fairing_approved, 0) AS final_fairing_approved,
        COALESCE(fq.final_quantity, 0) AS final_quantity,';

DECLARE @OldPeriodInspection nvarchar(max) = N'        COALESCE(SUM(d.receiving_total), 0) AS receiving_total,
        COALESCE(SUM(d.receiving_approved), 0) AS receiving_approved,
        COALESCE(SUM(d.receiving_quantity), 0) AS receiving_quantity,
        COALESCE(SUM(d.final_total), 0) AS final_total,
        COALESCE(SUM(d.final_approved), 0) AS final_approved,
        COALESCE(SUM(d.final_quantity), 0) AS final_quantity,';
DECLARE @NewPeriodInspection nvarchar(max) = N'        COALESCE(SUM(d.receiving_total), 0) AS receiving_total,
        COALESCE(SUM(d.receiving_approved), 0) AS receiving_approved,
        COALESCE(SUM(d.receiving_bumper_total), 0) AS receiving_bumper_total,
        COALESCE(SUM(d.receiving_bumper_approved), 0) AS receiving_bumper_approved,
        COALESCE(SUM(d.receiving_fairing_total), 0) AS receiving_fairing_total,
        COALESCE(SUM(d.receiving_fairing_approved), 0) AS receiving_fairing_approved,
        COALESCE(SUM(d.receiving_quantity), 0) AS receiving_quantity,
        COALESCE(SUM(d.final_total), 0) AS final_total,
        COALESCE(SUM(d.final_approved), 0) AS final_approved,
        COALESCE(SUM(d.final_fuka_total), 0) AS final_fuka_total,
        COALESCE(SUM(d.final_fuka_approved), 0) AS final_fuka_approved,
        COALESCE(SUM(d.final_bumper_total), 0) AS final_bumper_total,
        COALESCE(SUM(d.final_bumper_approved), 0) AS final_bumper_approved,
        COALESCE(SUM(d.final_fairing_total), 0) AS final_fairing_total,
        COALESCE(SUM(d.final_fairing_approved), 0) AS final_fairing_approved,
        COALESCE(SUM(d.final_quantity), 0) AS final_quantity,';

DECLARE @OldTrailerCte nvarchar(max) = N'        FROM RackClasses
        GROUP BY report_date
    )
    SELECT';
DECLARE @NewTrailerCte nvarchar(max) = N'        FROM RackClasses
        GROUP BY report_date
    ), TrailerDepartureDaily AS (
        SELECT
            CONVERT(date, d.TimeOut) AS report_date,
            COUNT_BIG(*) AS trailers_shipped
        FROM dbo.DriverLog AS d
        WHERE d.TimeOut >= CONVERT(datetime2(0), @HistoryStart)
          AND d.TimeOut < @WindowEndExclusive
          AND NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), d.TrailerID))), N'''') IS NOT NULL
        GROUP BY CONVERT(date, d.TimeOut)
    ), StagedRepaintCarts AS (
        SELECT DISTINCT e.cart_id
        FROM dbo.[EDI Data Table] AS e
        INNER JOIN dbo.[Master Data Table] AS m ON m.ID = e.[Part ID]
        LEFT JOIN dbo.tblCarts_Paint AS cp
            ON cp.[Cart ID] = e.cart_id
           AND cp.[Time Stamp] < @WindowEndExclusive
        WHERE e.cart_id IS NOT NULL
          AND e.Origin = N''F''
          AND cp.[Cart ID] IS NULL
          AND ISNULL(LTRIM(RTRIM(e.[Color])), N'''') <> N''''
          AND e.[Paint Block] NOT LIKE N''Arc%''
          AND ISNULL(m.RepaintCount, 0) > 0
          AND (e.insp_line_end_disposition IS NULL OR e.insp_line_end_disposition <> N''Approved'')
          AND e.cart_load_verified_stamp >= DATEADD(day, -6, CONVERT(datetime2(0), @ReportDate))
          AND e.cart_load_verified_stamp < @WindowEndExclusive
    ), StagedEligibleParts AS (
        SELECT
            LEFT(e.[Paint Block], 3) AS block_id,
            e.cart_id,
            e.cart_load_verified_stamp AS loaded_stamp,
            CASE
                WHEN ISNULL(e.Model, N'''') = N''Service'' THEN N''Svc''
                WHEN LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) = N''N33''
                  OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6171%'' THEN N''BV''
                ELSE N''Prd''
            END AS part_class,
            CASE WHEN rc.cart_id IS NULL THEN 0 ELSE 1 END AS has_repaint
        FROM dbo.[EDI Data Table] AS e
        LEFT JOIN dbo.tblCarts_Paint AS cp
            ON cp.[Cart ID] = e.cart_id
           AND cp.[Time Stamp] < @WindowEndExclusive
        LEFT JOIN StagedRepaintCarts AS rc ON rc.cart_id = e.cart_id
        WHERE e.cart_id IS NOT NULL
          AND e.Origin = N''F''
          AND cp.[Cart ID] IS NULL
          AND ISNULL(LTRIM(RTRIM(e.[Color])), N'''') <> N''''
          AND e.[Paint Block] NOT LIKE N''Arc%''
          AND (e.insp_line_end_disposition IS NULL OR e.insp_line_end_disposition = N''Repaint'')
          AND e.cart_load_verified_stamp >= DATEADD(day, -6, CONVERT(datetime2(0), @ReportDate))
          AND e.cart_load_verified_stamp < @WindowEndExclusive
    ), StagedCartGroups AS (
        SELECT
            block_id,
            cart_id,
            COUNT_BIG(*) AS piece_count,
            SUM(CASE WHEN part_class = N''Prd'' THEN 1 ELSE 0 END) AS production_piece_count,
            SUM(CASE WHEN part_class = N''BV'' THEN 1 ELSE 0 END) AS bv_piece_count,
            SUM(CASE WHEN part_class = N''Svc'' THEN 1 ELSE 0 END) AS service_piece_count,
            CASE
                WHEN MAX(CASE WHEN part_class = N''Svc'' THEN 1 ELSE 0 END) = 1 THEN N''Svc''
                WHEN MAX(CASE WHEN part_class = N''BV'' THEN 1 ELSE 0 END) = 1 THEN N''BV''
                ELSE N''Prd''
            END AS cart_class
        FROM StagedEligibleParts
        GROUP BY block_id, cart_id
        HAVING CONVERT(date, MIN(loaded_stamp)) >= DATEADD(day, -2, @ReportDate)
            OR (MAX(has_repaint) = 1 AND CONVERT(date, MIN(loaded_stamp)) >= DATEADD(day, -6, @ReportDate))
    ), StagedCurrent AS (
        SELECT
            @ReportDate AS report_date,
            COUNT_BIG(*) AS staged_carts,
            SUM(CASE WHEN cart_class = N''Prd'' THEN 1 ELSE 0 END) AS production_staged_carts,
            SUM(CASE WHEN cart_class = N''BV'' THEN 1 ELSE 0 END) AS bv_staged_carts,
            SUM(CASE WHEN cart_class = N''Svc'' THEN 1 ELSE 0 END) AS service_staged_carts,
            COALESCE(SUM(piece_count), 0) AS staged_pieces,
            COALESCE(SUM(production_piece_count), 0) AS production_staged_pieces,
            COALESCE(SUM(bv_piece_count), 0) AS bv_staged_pieces,
            COALESCE(SUM(service_piece_count), 0) AS service_staged_pieces
        FROM StagedCartGroups
    )
    SELECT';

DECLARE @OldDailyTrailer nvarchar(max) = N'        COALESCE(td.other_trailers_prepared, 0) AS other_trailers_prepared,
        COALESCE(rd.racks_shipped, 0) AS racks_shipped,';
DECLARE @NewDailyTrailer nvarchar(max) = N'        COALESCE(td.other_trailers_prepared, 0) AS other_trailers_prepared,
        COALESCE(tsd.trailers_shipped, 0) AS trailers_shipped,
        COALESCE(rd.racks_shipped, 0) AS racks_shipped,';

DECLARE @OldTrailerJoin nvarchar(max) = N'    LEFT JOIN TrailerDaily AS td ON td.report_date = d.report_date
    LEFT JOIN RackDaily AS rd ON rd.report_date = d.report_date';
DECLARE @NewTrailerJoin nvarchar(max) = N'    LEFT JOIN TrailerDaily AS td ON td.report_date = d.report_date
    LEFT JOIN StagedCurrent AS sc ON sc.report_date = d.report_date
    LEFT JOIN TrailerDepartureDaily AS tsd ON tsd.report_date = d.report_date
    LEFT JOIN RackDaily AS rd ON rd.report_date = d.report_date';

DECLARE @OldPeriodTrailer nvarchar(max) = N'        COALESCE(SUM(d.other_trailers_prepared), 0) AS other_trailers_prepared,
        COALESCE(SUM(d.racks_shipped), 0) AS racks_shipped,';
DECLARE @NewPeriodTrailer nvarchar(max) = N'        COALESCE(SUM(d.other_trailers_prepared), 0) AS other_trailers_prepared,
        COALESCE(SUM(d.trailers_shipped), 0) AS trailers_shipped,
        COALESCE(SUM(d.racks_shipped), 0) AS racks_shipped,';

DECLARE @OldPaintPass nvarchar(max) = N'        CASE WHEN pass_disposition IN (N''Repaint'', N''Direct Repaint'') THEN 1 ELSE 0 END AS is_repaint_failure,
        CASE WHEN pass_disposition = N''Approved'' THEN 1 ELSE 0 END AS is_eol_approved,';
DECLARE @NewPaintPass nvarchar(max) = N'        CASE WHEN pass_disposition IN (N''Repaint'', N''Direct Repaint'') THEN 1 ELSE 0 END AS is_repaint_failure,
        CASE WHEN pass_disposition = N''Repair'' THEN 1 ELSE 0 END AS is_finesse_repair,
        CASE WHEN pass_disposition = N''Approved'' THEN 1 ELSE 0 END AS is_eol_approved,';

DECLARE @OldPaintDaily nvarchar(max) = N'            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_repaint_failure = 1 AND p.repaint_line_set = N''Fairings'' THEN 1 ELSE 0 END) AS fairing_paint_fty_repaint_count,
            COUNT(*) AS reject_ppy_total,';
DECLARE @NewPaintDaily nvarchar(max) = N'            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_repaint_failure = 1 AND p.repaint_line_set = N''Fairings'' THEN 1 ELSE 0 END) AS fairing_paint_fty_repaint_count,
            SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_finesse_repair ELSE 0 END) AS paint_fty_repair_count,
            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_finesse_repair = 1 AND p.repaint_line_set = N''FUKA'' THEN 1 ELSE 0 END) AS fuka_paint_fty_repair_count,
            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_finesse_repair = 1 AND p.repaint_line_set = N''Fairings'' THEN 1 ELSE 0 END) AS fairing_paint_fty_repair_count,
            SUM(CASE WHEN p.is_initial_pass = 1 AND p.is_finesse_repair = 1 AND p.repaint_line_set = N''Bumpers'' THEN 1 ELSE 0 END) AS bumper_paint_fty_repair_count,
            COUNT(*) AS reject_ppy_total,';

DECLARE @OldDailyFinesse nvarchar(max) = N'        COALESCE(p.fairing_paint_fty_repaint_count, 0) AS fairing_paint_fty_repaint_count,
        COALESCE(p.reject_ppy_total, 0) AS reject_ppy_total,';
DECLARE @NewDailyFinesse nvarchar(max) = N'        COALESCE(p.fairing_paint_fty_repaint_count, 0) AS fairing_paint_fty_repaint_count,
        COALESCE(p.paint_fty_repair_count, 0) AS paint_fty_repair_count,
        COALESCE(p.fuka_paint_fty_repair_count, 0) AS fuka_paint_fty_repair_count,
        COALESCE(p.fairing_paint_fty_repair_count, 0) AS fairing_paint_fty_repair_count,
        COALESCE(p.bumper_paint_fty_repair_count, 0) AS bumper_paint_fty_repair_count,
        COALESCE(p.reject_ppy_total, 0) AS reject_ppy_total,';

DECLARE @OldPeriodFinesse nvarchar(max) = N'        COALESCE(SUM(d.fairing_paint_fty_repaint_count), 0) AS fairing_paint_fty_repaint_count,
        COALESCE(SUM(d.reject_ppy_total), 0) AS reject_ppy_total,';
DECLARE @NewPeriodFinesse nvarchar(max) = N'        COALESCE(SUM(d.fairing_paint_fty_repaint_count), 0) AS fairing_paint_fty_repaint_count,
        COALESCE(SUM(d.paint_fty_repair_count), 0) AS paint_fty_repair_count,
        COALESCE(SUM(d.fuka_paint_fty_repair_count), 0) AS fuka_paint_fty_repair_count,
        COALESCE(SUM(d.fairing_paint_fty_repair_count), 0) AS fairing_paint_fty_repair_count,
        COALESCE(SUM(d.bumper_paint_fty_repair_count), 0) AS bumper_paint_fty_repair_count,
        COALESCE(SUM(d.reject_ppy_total), 0) AS reject_ppy_total,';

DECLARE @OldDailyStaged nvarchar(max) = N'        COALESCE(l.n71_6164_carts_loaded, 0) AS n71_6164_carts_loaded,
        COALESCE(px.paint_processed, 0) AS paint_processed,';
DECLARE @NewDailyStaged nvarchar(max) = N'        COALESCE(l.n71_6164_carts_loaded, 0) AS n71_6164_carts_loaded,
        COALESCE(sc.staged_carts, 0) AS staged_carts,
        COALESCE(sc.production_staged_carts, 0) AS production_staged_carts,
        COALESCE(sc.bv_staged_carts, 0) AS bv_staged_carts,
        COALESCE(sc.service_staged_carts, 0) AS service_staged_carts,
        COALESCE(sc.staged_pieces, 0) AS staged_pieces,
        COALESCE(sc.production_staged_pieces, 0) AS production_staged_pieces,
        COALESCE(sc.bv_staged_pieces, 0) AS bv_staged_pieces,
        COALESCE(sc.service_staged_pieces, 0) AS service_staged_pieces,
        COALESCE(px.paint_processed, 0) AS paint_processed,';

DECLARE @OldPeriodStaged nvarchar(max) = N'        COALESCE(SUM(d.n71_6164_carts_loaded), 0) AS n71_6164_carts_loaded,
        COALESCE(SUM(d.paint_processed), 0) AS paint_processed,';
DECLARE @NewPeriodStaged nvarchar(max) = N'        COALESCE(SUM(d.n71_6164_carts_loaded), 0) AS n71_6164_carts_loaded,
        COALESCE(SUM(d.staged_carts), 0) AS staged_carts,
        COALESCE(SUM(d.production_staged_carts), 0) AS production_staged_carts,
        COALESCE(SUM(d.bv_staged_carts), 0) AS bv_staged_carts,
        COALESCE(SUM(d.service_staged_carts), 0) AS service_staged_carts,
        COALESCE(SUM(d.staged_pieces), 0) AS staged_pieces,
        COALESCE(SUM(d.production_staged_pieces), 0) AS production_staged_pieces,
        COALESCE(SUM(d.bv_staged_pieces), 0) AS bv_staged_pieces,
        COALESCE(SUM(d.service_staged_pieces), 0) AS service_staged_pieces,
        COALESCE(SUM(d.paint_processed), 0) AS paint_processed,';

DECLARE @PatchOrder int;
DECLARE @SourceToken nvarchar(max);
DECLARE @TargetToken nvarchar(max);
DECLARE patch_cursor CURSOR LOCAL FAST_FORWARD FOR
    SELECT
        patch_order,
        CASE WHEN @RollbackChange = 1 THEN new_token ELSE old_token END,
        CASE WHEN @RollbackChange = 1 THEN old_token ELSE new_token END
    FROM (VALUES
        (1, @OldReceiving, @NewReceiving),
        (2, @OldFinal, @NewFinal),
        (3, @OldDailyInspection, @NewDailyInspection),
        (4, @OldPeriodInspection, @NewPeriodInspection),
        (5, @OldTrailerCte, @NewTrailerCte),
        (6, @OldDailyTrailer, @NewDailyTrailer),
        (7, @OldTrailerJoin, @NewTrailerJoin),
        (8, @OldPeriodTrailer, @NewPeriodTrailer),
        (9, @OldPaintPass, @NewPaintPass),
        (10, @OldPaintDaily, @NewPaintDaily),
        (11, @OldDailyFinesse, @NewDailyFinesse),
        (12, @OldPeriodFinesse, @NewPeriodFinesse),
        (13, @OldDailyStaged, @NewDailyStaged),
        (14, @OldPeriodStaged, @NewPeriodStaged)
    ) AS patch(patch_order, old_token, new_token)
    ORDER BY patch_order;

OPEN patch_cursor;
FETCH NEXT FROM patch_cursor INTO @PatchOrder, @SourceToken, @TargetToken;
WHILE @@FETCH_STATUS = 0
BEGIN
    IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @SourceToken, N''))) / NULLIF(LEN(@SourceToken), 0) <> 1
        THROW 53303, 'Dashboard trailer/inspection patch token count mismatch.', 1;
    SET @CandidateDefinition = REPLACE(@CandidateDefinition, @SourceToken, @TargetToken);
    FETCH NEXT FROM patch_cursor INTO @PatchOrder, @SourceToken, @TargetToken;
END;
CLOSE patch_cursor;
DEALLOCATE patch_cursor;

BEGIN TRANSACTION;

EXEC sys.sp_executesql @CandidateDefinition;

DECLARE @ObservedNewDefinition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedNewHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@ObservedNewDefinition, N''))), 2);

IF @ObservedNewHash <> @ExpectedNewHash
    THROW 53304, 'Dashboard trailer/inspection-detail candidate hash mismatch.', 1;

IF @CommitChange = 1
    COMMIT TRANSACTION;
ELSE
    ROLLBACK TRANSACTION;

SELECT
    marker = CASE
        WHEN @RollbackChange = 1 THEN N'ASTER_OPERATIONS_KPI_TRAILER_INSPECTION_DETAILS_ROLLBACK_V1'
        ELSE N'ASTER_OPERATIONS_KPI_TRAILER_INSPECTION_DETAILS_FORWARD_V1'
    END,
    old_hash = @ObservedOldHash,
    new_hash = @ObservedNewHash,
    committed = @CommitChange,
    rollback_mode = @RollbackChange;
