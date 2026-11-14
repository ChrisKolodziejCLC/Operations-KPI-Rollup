/*
    Reversible aggregate-only correction for Operations KPI product families.

    The previous dashboard inferred Bumpers/Fairings from EDI Origin. Live
    source evidence proved that Origin mixes both product families. This patch
    uses the authoritative EDI Description values consistently:
      Fender          -> FUKA
      Bumper          -> Bumpers
      Chassis Fairing -> Fairings

    N71-6164 remains a separately requested shipping/rack subset and takes
    precedence there. No QPTS business rows or permissions are changed.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @RollbackChange bit = 0;
DECLARE @BaseHash varchar(64) = '21149FDE5DB32871914F9846F6E29FCF7D071BC6189D7A2272E9E7E4FC0C2DF3';
DECLARE @CorrectedHash varchar(64) = '5A4EA0319892EF663E13ED7EA8BC026D852F3DCC748EC450896B6D549464044D';
DECLARE @ExpectedOldHash varchar(64) = CASE WHEN @RollbackChange = 1 THEN @CorrectedHash ELSE @BaseHash END;
DECLARE @ExpectedNewHash varchar(64) = CASE WHEN @RollbackChange = 1 THEN @BaseHash ELSE @CorrectedHash END;
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @OldDefinition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedOldHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@OldDefinition, N''))), 2);

IF @ObservedOldHash <> @ExpectedOldHash
    THROW 53401, 'Dashboard product-family pre-change hash mismatch.', 1;

DECLARE @CandidateDefinition nvarchar(max) = @OldDefinition;
DECLARE @CreateHeader nvarchar(256) = N'CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @AlterHeader nvarchar(256) = N'ALTER   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';

IF CHARINDEX(@CreateHeader, @CandidateDefinition) > 0
    SET @CandidateDefinition = REPLACE(@CandidateDefinition, @CreateHeader, @AlterHeader);
ELSE IF CHARINDEX(@AlterHeader, @CandidateDefinition) = 0
    THROW 53402, 'Dashboard procedure header is not in the reviewed shape.', 1;

DECLARE @OldPaintFamily nvarchar(max) = N'        CASE
            WHEN CONVERT(nvarchar(10), e.Origin) = N''B'' THEN N''Bumpers''
            WHEN CONVERT(nvarchar(10), e.Origin) = N''F''
             AND (LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71%''
               OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N33%'') THEN N''Fairings''
            ELSE N''FUKA''
        END AS repaint_line_set';
DECLARE @NewPaintFamily nvarchar(max) = N'        CASE
            WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Fender'' THEN N''FUKA''
            WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Bumper'' THEN N''Bumpers''
            WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Chassis Fairing'' THEN N''Fairings''
            ELSE N''Other''
        END AS repaint_line_set';

DECLARE @OldInspectionFamily nvarchar(max) = N'            CASE
                WHEN CONVERT(nvarchar(10), e.Origin) = N''B'' THEN N''Bumpers''
                WHEN CONVERT(nvarchar(10), e.Origin) = N''F''
                 AND (LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71%''
                   OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N33%'') THEN N''Fairings''
                ELSE N''FUKA''
            END AS inspection_line_set,';
DECLARE @NewInspectionFamily nvarchar(max) = N'            CASE
                WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Fender'' THEN N''FUKA''
                WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Bumper'' THEN N''Bumpers''
                WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Chassis Fairing'' THEN N''Fairings''
                ELSE N''Other''
            END AS inspection_line_set,';

DECLARE @OldBumperShipped nvarchar(max) = N'            COUNT(DISTINCT CASE WHEN CONVERT(nvarchar(10), e.Origin) = N''B'' THEN e.[Part ID] END) AS bumpers_shipped';
DECLARE @NewBumperShipped nvarchar(max) = N'            COUNT(DISTINCT CASE WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Bumper'' THEN e.[Part ID] END) AS bumpers_shipped';

DECLARE @OldRackFamily nvarchar(max) = N'            SUM(CASE
                WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6164%'' THEN 0
                WHEN CONVERT(nvarchar(10), e.Origin) = N''B'' THEN 0
                WHEN CONVERT(nvarchar(10), e.Origin) = N''F''
                 AND (LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71%''
                   OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N33%'') THEN 0
                ELSE 1
            END) AS fuka_parts,
            SUM(CASE
                WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6164%'' THEN 0
                WHEN CONVERT(nvarchar(10), e.Origin) = N''B'' THEN 1 ELSE 0
            END) AS bumper_parts,
            SUM(CASE
                WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6164%'' THEN 0
                WHEN CONVERT(nvarchar(10), e.Origin) = N''F''
                 AND (LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71%''
                   OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N33%'') THEN 1
                ELSE 0
            END) AS fairing_parts';
DECLARE @NewRackFamily nvarchar(max) = N'            SUM(CASE
                WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6164%'' THEN 0
                WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Fender'' THEN 1 ELSE 0
            END) AS fuka_parts,
            SUM(CASE
                WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6164%'' THEN 0
                WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Bumper'' THEN 1 ELSE 0
            END) AS bumper_parts,
            SUM(CASE
                WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6164%'' THEN 0
                WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Chassis Fairing'' THEN 1 ELSE 0
            END) AS fairing_parts';

DECLARE @OldShippingFamily nvarchar(max) = N'        CASE
            WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6164%'' THEN N''N71-6164''
            WHEN CONVERT(nvarchar(10), e.Origin) = N''B'' THEN N''Bumpers''
            WHEN CONVERT(nvarchar(10), e.Origin) = N''F'' AND (LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71%'' OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N33%'') THEN N''Fairings''
            ELSE N''FUKA''
        END';
DECLARE @NewShippingFamily nvarchar(max) = N'        CASE
            WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6164%'' THEN N''N71-6164''
            WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Fender'' THEN N''FUKA''
            WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Bumper'' THEN N''Bumpers''
            WHEN LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Chassis Fairing'' THEN N''Fairings''
            ELSE N''Other''
        END';

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
        (1, @OldPaintFamily, @NewPaintFamily, 1),
        (2, @OldInspectionFamily, @NewInspectionFamily, 2),
        (3, @OldBumperShipped, @NewBumperShipped, 1),
        (4, @OldRackFamily, @NewRackFamily, 1),
        (5, @OldShippingFamily, @NewShippingFamily, 2)
    ) AS patch(patch_order, old_token, new_token, expected_count)
    ORDER BY patch_order;

OPEN patch_cursor;
FETCH NEXT FROM patch_cursor INTO @PatchOrder, @SourceToken, @TargetToken, @ExpectedCount;
WHILE @@FETCH_STATUS = 0
BEGIN
    IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @SourceToken, N''))) / NULLIF(LEN(@SourceToken), 0) <> @ExpectedCount
        THROW 53403, 'Dashboard product-family patch token count mismatch.', 1;
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
    THROW 53404, 'Dashboard product-family candidate hash mismatch.', 1;

IF @CommitChange = 1
    COMMIT TRANSACTION;
ELSE
    ROLLBACK TRANSACTION;

SELECT
    marker = CASE
        WHEN @RollbackChange = 1 THEN N'ASTER_OPERATIONS_KPI_PRODUCT_FAMILY_ROLLBACK_V1'
        ELSE N'ASTER_OPERATIONS_KPI_PRODUCT_FAMILY_FORWARD_V1'
    END,
    old_hash = @ObservedOldHash,
    new_hash = @ObservedNewHash,
    committed = @CommitChange,
    rollback_mode = @RollbackChange;
