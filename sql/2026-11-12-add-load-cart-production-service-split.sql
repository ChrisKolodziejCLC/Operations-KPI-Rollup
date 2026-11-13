/*
    Hash-gated extension of the approved Operations KPI rollup.

    Preview mode is committed first. It changes the procedure only inside a
    transaction, reports the candidate and rollback hashes, and rolls back.
    The reviewed hashes are pinned before production application.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 0;
DECLARE @ExpectedOldHash varchar(64) = '5351EF835346688E38430FDBC06F6EF35C314A7DA1BC5E9240D1379C08CA7A36';
DECLARE @ExpectedNewHash varchar(64) = NULL;
DECLARE @ExpectedRollbackHash varchar(64) = '5351EF835346688E38430FDBC06F6EF35C314A7DA1BC5E9240D1379C08CA7A36';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @LF nchar(1) = NCHAR(10);
DECLARE @Definition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedOldHash varchar(64) = CONVERT(
    varchar(64),
    HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@Definition, N''))),
    2
);
DECLARE @CandidateHash varchar(64);
DECLARE @RollbackHash varchar(64);

IF @Definition IS NULL
    THROW 51200, 'The approved Operations KPI rollup procedure is absent.', 1;
IF @ObservedOldHash <> @ExpectedOldHash
    THROW 51201, 'The Operations KPI rollup procedure does not match the reviewed pre-change hash.', 1;

DECLARE @OldCreate nvarchar(max) = N'CREATE   PROCEDURE';
DECLARE @NewCreate nvarchar(max) = N'ALTER   PROCEDURE';

DECLARE @OldLoaded nvarchar(max) =
    N'), LoadedDaily AS (' + @LF +
    N'        SELECT' + @LF +
    N'            h.moment_date AS report_date,' + @LF +
    N'            COUNT(*) AS parts_loaded,' + @LF +
    N'            SUM(CASE WHEN service_part.part_id IS NULL THEN 1 ELSE 0 END) AS production_parts_loaded,' + @LF +
    N'            SUM(CASE WHEN service_part.part_id IS NULL THEN 0 ELSE 1 END) AS service_parts_loaded,' + @LF +
    N'            COUNT(DISTINCT h.PaintCart_ID) AS carts_loaded' + @LF +
    N'        FROM #HistoryAll AS h' + @LF +
    N'        LEFT JOIN (' + @LF +
    N'            SELECT DISTINCT [Part ID] AS part_id' + @LF +
    N'            FROM dbo.[EDI Data Table]' + @LF +
    N'            WHERE ISNULL(Model, N'''') = N''Service''' + @LF +
    N'        ) AS service_part' + @LF +
    N'            ON service_part.part_id = h.part_id' + @LF +
    N'        WHERE h.moment_category IN (N''load_line'', N''load_line_repaint'')' + @LF +
    N'        GROUP BY h.moment_date';

DECLARE @NewLoaded nvarchar(max) =
    N'), LoadedDaily AS (' + @LF +
    N'        SELECT' + @LF +
    N'            h.moment_date AS report_date,' + @LF +
    N'            COUNT(*) AS parts_loaded,' + @LF +
    N'            SUM(CASE WHEN service_part.part_id IS NULL THEN 1 ELSE 0 END) AS production_parts_loaded,' + @LF +
    N'            SUM(CASE WHEN service_part.part_id IS NULL THEN 0 ELSE 1 END) AS service_parts_loaded,' + @LF +
    N'            COUNT(DISTINCT CASE WHEN service_part.part_id IS NULL THEN h.PaintCart_ID END) AS production_carts_loaded,' + @LF +
    N'            COUNT(DISTINCT CASE WHEN service_part.part_id IS NULL THEN NULL ELSE h.PaintCart_ID END) AS service_carts_loaded,' + @LF +
    N'            COUNT(DISTINCT h.PaintCart_ID) AS carts_loaded' + @LF +
    N'        FROM #HistoryAll AS h' + @LF +
    N'        LEFT JOIN (' + @LF +
    N'            SELECT DISTINCT [Part ID] AS part_id' + @LF +
    N'            FROM dbo.[EDI Data Table]' + @LF +
    N'            WHERE ISNULL(Model, N'''') = N''Service''' + @LF +
    N'        ) AS service_part' + @LF +
    N'            ON service_part.part_id = h.part_id' + @LF +
    N'        WHERE h.moment_category IN (N''load_line'', N''load_line_repaint'')' + @LF +
    N'        GROUP BY h.moment_date';

DECLARE @OldDailySelect nvarchar(max) =
    N'        COALESCE(l.parts_loaded, 0) AS parts_loaded,' + @LF +
    N'        COALESCE(l.production_parts_loaded, 0) AS production_parts_loaded,' + @LF +
    N'        COALESCE(l.service_parts_loaded, 0) AS service_parts_loaded,' + @LF +
    N'        COALESCE(l.carts_loaded, 0) AS carts_loaded,';

DECLARE @NewDailySelect nvarchar(max) =
    N'        COALESCE(l.parts_loaded, 0) AS parts_loaded,' + @LF +
    N'        COALESCE(l.production_parts_loaded, 0) AS production_parts_loaded,' + @LF +
    N'        COALESCE(l.service_parts_loaded, 0) AS service_parts_loaded,' + @LF +
    N'        COALESCE(l.carts_loaded, 0) AS carts_loaded,' + @LF +
    N'        COALESCE(l.production_carts_loaded, 0) AS production_carts_loaded,' + @LF +
    N'        COALESCE(l.service_carts_loaded, 0) AS service_carts_loaded,';

DECLARE @OldPeriodSelect nvarchar(max) =
    N'        COALESCE(SUM(d.parts_loaded), 0) AS parts_loaded,' + @LF +
    N'        COALESCE(SUM(d.production_parts_loaded), 0) AS production_parts_loaded,' + @LF +
    N'        COALESCE(SUM(d.service_parts_loaded), 0) AS service_parts_loaded,' + @LF +
    N'        COALESCE(SUM(d.carts_loaded), 0) AS carts_loaded,';

DECLARE @NewPeriodSelect nvarchar(max) =
    N'        COALESCE(SUM(d.parts_loaded), 0) AS parts_loaded,' + @LF +
    N'        COALESCE(SUM(d.production_parts_loaded), 0) AS production_parts_loaded,' + @LF +
    N'        COALESCE(SUM(d.service_parts_loaded), 0) AS service_parts_loaded,' + @LF +
    N'        COALESCE(SUM(d.carts_loaded), 0) AS carts_loaded,' + @LF +
    N'        COALESCE(SUM(d.production_carts_loaded), 0) AS production_carts_loaded,' + @LF +
    N'        COALESCE(SUM(d.service_carts_loaded), 0) AS service_carts_loaded,';

IF (LEN(@Definition) - LEN(REPLACE(@Definition, @OldCreate, N''))) / LEN(@OldCreate) <> 1
    THROW 51202, 'Expected exactly one CREATE PROCEDURE marker.', 1;
IF (LEN(@Definition) - LEN(REPLACE(@Definition, @OldLoaded, N''))) / LEN(@OldLoaded) <> 1
    THROW 51203, 'Expected exactly one reviewed LoadedDaily block.', 1;
IF (LEN(@Definition) - LEN(REPLACE(@Definition, @OldDailySelect, N''))) / LEN(@OldDailySelect) <> 1
    THROW 51204, 'Expected exactly one reviewed daily load projection.', 1;
IF (LEN(@Definition) - LEN(REPLACE(@Definition, @OldPeriodSelect, N''))) / LEN(@OldPeriodSelect) <> 1
    THROW 51205, 'Expected exactly one reviewed period load projection.', 1;

SET @Definition = REPLACE(@Definition, @OldCreate, @NewCreate);
SET @Definition = REPLACE(@Definition, @OldLoaded, @NewLoaded);
SET @Definition = REPLACE(@Definition, @OldDailySelect, @NewDailySelect);
SET @Definition = REPLACE(@Definition, @OldPeriodSelect, @NewPeriodSelect);

BEGIN TRY
    BEGIN TRANSACTION;
    EXEC sys.sp_executesql @Definition;

    DECLARE @StoredDefinition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
    SET @CandidateHash = CONVERT(
        varchar(64),
        HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@StoredDefinition, N''))),
        2
    );

    IF @ExpectedNewHash IS NOT NULL AND @CandidateHash <> @ExpectedNewHash
        THROW 51206, 'The applied procedure hash does not match the reviewed candidate hash.', 1;
    IF @StoredDefinition NOT LIKE N'%production_carts_loaded%'
       OR @StoredDefinition NOT LIKE N'%service_carts_loaded%'
        THROW 51207, 'The applied procedure is missing the approved cart split.', 1;

    DECLARE @RollbackDefinition nvarchar(max) = @StoredDefinition;
    SET @RollbackDefinition = REPLACE(@RollbackDefinition, @NewLoaded, @OldLoaded);
    SET @RollbackDefinition = REPLACE(@RollbackDefinition, @NewDailySelect, @OldDailySelect);
    SET @RollbackDefinition = REPLACE(@RollbackDefinition, @NewPeriodSelect, @OldPeriodSelect);
    SET @RollbackHash = CONVERT(
        varchar(64),
        HASHBYTES('SHA2_256', CONVERT(varbinary(max), @RollbackDefinition)),
        2
    );

    IF @ExpectedRollbackHash IS NOT NULL AND @RollbackHash <> @ExpectedRollbackHash
        THROW 51208, 'The calculated rollback hash does not match the reviewed rollback hash.', 1;

    IF @CommitChange = 1
        COMMIT TRANSACTION;
    ELSE
        ROLLBACK TRANSACTION;

    SELECT
        Marker = N'ASTER_OPERATIONS_KPI_CART_SPLIT_V1',
        Applied = @CommitChange,
        PreChangeHash = @ObservedOldHash,
        CandidateHash = @CandidateHash,
        RollbackHash = @RollbackHash;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
