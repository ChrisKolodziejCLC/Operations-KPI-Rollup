/*
    Reversible aggregate-only correction for the Operations KPI Finesse tile.

    Finesse starts with each part's first Receiving decision. Rejected parts
    remain in that cohort even when repaint later changes current Origin from
    Brownsville (B) to Grand Prairie (F). Completed repair is repair_disposition
    Repaired; WFP or a current Repaint disposition is repaint; all other reject
    outcomes remain pending. Pending is excluded from the displayed percentage.

    No QPTS business rows or permissions are changed.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @RollbackChange bit = 0;
DECLARE @BaseHash varchar(64) = '5A4EA0319892EF663E13ED7EA8BC026D852F3DCC748EC450896B6D549464044D';
DECLARE @CorrectedHash varchar(64) = 'AC7DFDADC5C86C638385CD59265DA5E78A35C6A6A50F7CD869A014F7F02639BE';
DECLARE @ExpectedOldHash varchar(64) = CASE WHEN @RollbackChange = 1 THEN @CorrectedHash ELSE @BaseHash END;
DECLARE @ExpectedNewHash varchar(64) = CASE WHEN @RollbackChange = 1 THEN @BaseHash ELSE @CorrectedHash END;
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @OldDefinition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedOldHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@OldDefinition, N''))), 2);

IF @ObservedOldHash <> @ExpectedOldHash
    THROW 53501, 'Dashboard Receiving/Finesse pre-change hash mismatch.', 1;

DECLARE @CandidateDefinition nvarchar(max) = @OldDefinition;
DECLARE @CreateHeader nvarchar(256) = N'CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @AlterHeader nvarchar(256) = N'ALTER   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';

IF CHARINDEX(@CreateHeader, @CandidateDefinition) > 0
    SET @CandidateDefinition = REPLACE(@CandidateDefinition, @CreateHeader, @AlterHeader);
ELSE IF CHARINDEX(@AlterHeader, @CandidateDefinition) = 0
    THROW 53502, 'Dashboard procedure header is not in the reviewed shape.', 1;

DECLARE @OldReceivingComment nvarchar(max) = N'    /* First receiving decision per part, split by requested product family. */';
DECLARE @NewReceivingComment nvarchar(max) = N'    /*
       First receiving decision per part. Finesse follows rejected parts from
       that immutable cohort even when repaint later changes current Origin.
    */';

DECLARE @OldReceivingOutcome nvarchar(max) = N'            END AS inspection_line_set,
            ROW_NUMBER() OVER (PARTITION BY h.part_id ORDER BY h.moment_at, h.id) AS rn
        FROM #History AS h
        INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = h.part_id
        WHERE h.moment_category IN (N''receiving_approved'', N''receiving_reject'')';
DECLARE @NewReceivingOutcome nvarchar(max) = N'            END AS inspection_line_set,
            CASE
                WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.repair_disposition))) = N''Repaired'' THEN N''Repaired''
                WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.repair_disposition))) = N''WFP''
                  OR LTRIM(RTRIM(CONVERT(nvarchar(255), e.insp_line_end_disposition))) = N''Repaint'' THEN N''Repaint''
                ELSE N''Pending''
            END AS finesse_outcome,
            ROW_NUMBER() OVER (PARTITION BY h.part_id ORDER BY h.moment_at, h.id) AS rn
        FROM #History AS h
        INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = h.part_id
        WHERE h.moment_category IN (N''receiving_approved'', N''receiving_reject'')';

DECLARE @OldReceivingCounts nvarchar(max) = N'        SUM(CASE WHEN inspection_line_set = N''Fairings'' AND moment_category = N''receiving_approved'' THEN 1 ELSE 0 END) AS receiving_fairing_approved';
DECLARE @NewReceivingCounts nvarchar(max) = N'        SUM(CASE WHEN inspection_line_set = N''Fairings'' AND moment_category = N''receiving_approved'' THEN 1 ELSE 0 END) AS receiving_fairing_approved,
        SUM(CASE WHEN moment_category = N''receiving_reject'' THEN 1 ELSE 0 END) AS finesse_rejected_count,
        SUM(CASE WHEN moment_category = N''receiving_reject'' AND finesse_outcome = N''Repaired'' THEN 1 ELSE 0 END) AS finesse_repair_count,
        SUM(CASE WHEN moment_category = N''receiving_reject'' AND finesse_outcome = N''Repaint'' THEN 1 ELSE 0 END) AS finesse_repaint_count,
        SUM(CASE WHEN moment_category = N''receiving_reject'' AND finesse_outcome = N''Pending'' THEN 1 ELSE 0 END) AS finesse_pending_count,
        SUM(CASE WHEN moment_category = N''receiving_reject'' AND finesse_outcome = N''Repaired'' AND inspection_line_set = N''Bumpers'' THEN 1 ELSE 0 END) AS bumper_finesse_repair_count,
        SUM(CASE WHEN moment_category = N''receiving_reject'' AND finesse_outcome = N''Repaired'' AND inspection_line_set = N''Fairings'' THEN 1 ELSE 0 END) AS fairing_finesse_repair_count,
        SUM(CASE WHEN moment_category = N''receiving_reject'' AND finesse_outcome = N''Repaired'' AND inspection_line_set NOT IN (N''Bumpers'', N''Fairings'') THEN 1 ELSE 0 END) AS other_finesse_repair_count';

DECLARE @OldDailyFields nvarchar(max) = N'        COALESCE(r.receiving_fairing_approved, 0) AS receiving_fairing_approved,
        COALESCE(rq.receiving_quantity, 0) AS receiving_quantity,';
DECLARE @NewDailyFields nvarchar(max) = N'        COALESCE(r.receiving_fairing_approved, 0) AS receiving_fairing_approved,
        COALESCE(r.finesse_rejected_count, 0) AS finesse_rejected_count,
        COALESCE(r.finesse_repair_count, 0) AS finesse_repair_count,
        COALESCE(r.finesse_repaint_count, 0) AS finesse_repaint_count,
        COALESCE(r.finesse_pending_count, 0) AS finesse_pending_count,
        COALESCE(r.bumper_finesse_repair_count, 0) AS bumper_finesse_repair_count,
        COALESCE(r.fairing_finesse_repair_count, 0) AS fairing_finesse_repair_count,
        COALESCE(r.other_finesse_repair_count, 0) AS other_finesse_repair_count,
        COALESCE(rq.receiving_quantity, 0) AS receiving_quantity,';

DECLARE @OldPeriodFields nvarchar(max) = N'        COALESCE(SUM(d.receiving_fairing_approved), 0) AS receiving_fairing_approved,
        COALESCE(SUM(d.receiving_quantity), 0) AS receiving_quantity,';
DECLARE @NewPeriodFields nvarchar(max) = N'        COALESCE(SUM(d.receiving_fairing_approved), 0) AS receiving_fairing_approved,
        COALESCE(SUM(d.finesse_rejected_count), 0) AS finesse_rejected_count,
        COALESCE(SUM(d.finesse_repair_count), 0) AS finesse_repair_count,
        COALESCE(SUM(d.finesse_repaint_count), 0) AS finesse_repaint_count,
        COALESCE(SUM(d.finesse_pending_count), 0) AS finesse_pending_count,
        COALESCE(SUM(d.bumper_finesse_repair_count), 0) AS bumper_finesse_repair_count,
        COALESCE(SUM(d.fairing_finesse_repair_count), 0) AS fairing_finesse_repair_count,
        COALESCE(SUM(d.other_finesse_repair_count), 0) AS other_finesse_repair_count,
        COALESCE(SUM(d.receiving_quantity), 0) AS receiving_quantity,';

DECLARE @PatchOrder int;
DECLARE @SourceToken nvarchar(max);
DECLARE @TargetToken nvarchar(max);
DECLARE @ExpectedCount int;
DECLARE patch_cursor CURSOR LOCAL FAST_FORWARD FOR
    SELECT
        patch_order,
        CASE WHEN @RollbackChange = 1 THEN new_token ELSE old_token END,
        CASE WHEN @RollbackChange = 1 THEN old_token ELSE new_token END,
        expected_count
    FROM (VALUES
        (1, @OldReceivingComment, @NewReceivingComment, 1),
        (2, @OldReceivingOutcome, @NewReceivingOutcome, 1),
        (3, @OldReceivingCounts, @NewReceivingCounts, 1),
        (4, @OldDailyFields, @NewDailyFields, 1),
        (5, @OldPeriodFields, @NewPeriodFields, 1)
    ) AS patch(patch_order, old_token, new_token, expected_count)
    ORDER BY patch_order;

OPEN patch_cursor;
FETCH NEXT FROM patch_cursor INTO @PatchOrder, @SourceToken, @TargetToken, @ExpectedCount;
WHILE @@FETCH_STATUS = 0
BEGIN
    IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @SourceToken, N''))) / NULLIF(LEN(@SourceToken), 0) <> @ExpectedCount
        THROW 53503, 'Dashboard Receiving/Finesse patch token count mismatch.', 1;
    SET @CandidateDefinition = REPLACE(@CandidateDefinition, @SourceToken, @TargetToken);
    FETCH NEXT FROM patch_cursor INTO @PatchOrder, @SourceToken, @TargetToken, @ExpectedCount;
END;
CLOSE patch_cursor;
DEALLOCATE patch_cursor;

BEGIN TRANSACTION;
EXEC sys.sp_executesql @CandidateDefinition;

DECLARE @ObservedNewDefinition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedNewHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@ObservedNewDefinition, N''))), 2);

IF @ObservedNewHash <> @ExpectedNewHash
    THROW 53504, 'Dashboard Receiving/Finesse candidate hash mismatch.', 1;

IF @CommitChange = 1
    COMMIT TRANSACTION;
ELSE
    ROLLBACK TRANSACTION;

SELECT
    marker = CASE
        WHEN @RollbackChange = 1 THEN N'ASTER_OPERATIONS_KPI_RECEIVING_FINESSE_ROLLBACK_V1'
        ELSE N'ASTER_OPERATIONS_KPI_RECEIVING_FINESSE_FORWARD_V1'
    END,
    old_hash = @ObservedOldHash,
    new_hash = @ObservedNewHash,
    committed = @CommitChange,
    rollback_mode = @RollbackChange;
