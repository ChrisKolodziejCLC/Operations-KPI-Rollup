/* Reverse only the reviewed 2026-11-12 load cart production/service split. */
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @ExpectedCurrentHash varchar(64) = 'A733058BF6F816A07D9D6249BC0B1BCCC00EFA26ECEA1F98A0390E682AA9AB88';
DECLARE @ExpectedRollbackHash varchar(64) = '5351EF835346688E38430FDBC06F6EF35C314A7DA1BC5E9240D1379C08CA7A36';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @LF nchar(1) = NCHAR(10);
DECLARE @Definition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedCurrentHash varchar(64) = CONVERT(
    varchar(64),
    HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@Definition, N''))),
    2
);

IF @Definition IS NULL
    THROW 51300, 'The approved Operations KPI rollup procedure is absent.', 1;
IF @ObservedCurrentHash <> @ExpectedCurrentHash
    THROW 51301, 'The Operations KPI rollup procedure does not match the reviewed cart-split hash.', 1;

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
    THROW 51302, 'Expected exactly one CREATE PROCEDURE marker.', 1;
IF (LEN(@Definition) - LEN(REPLACE(@Definition, @NewLoaded, N''))) / LEN(@NewLoaded) <> 1
    THROW 51303, 'Expected exactly one reviewed cart-split LoadedDaily block.', 1;
IF (LEN(@Definition) - LEN(REPLACE(@Definition, @NewDailySelect, N''))) / LEN(@NewDailySelect) <> 1
    THROW 51304, 'Expected exactly one reviewed cart-split daily projection.', 1;
IF (LEN(@Definition) - LEN(REPLACE(@Definition, @NewPeriodSelect, N''))) / LEN(@NewPeriodSelect) <> 1
    THROW 51305, 'Expected exactly one reviewed cart-split period projection.', 1;

SET @Definition = REPLACE(@Definition, @OldCreate, @NewCreate);
SET @Definition = REPLACE(@Definition, @NewLoaded, @OldLoaded);
SET @Definition = REPLACE(@Definition, @NewDailySelect, @OldDailySelect);
SET @Definition = REPLACE(@Definition, @NewPeriodSelect, @OldPeriodSelect);

BEGIN TRY
    BEGIN TRANSACTION;
    EXEC sys.sp_executesql @Definition;

    DECLARE @ObservedRollbackHash varchar(64) = CONVERT(
        varchar(64),
        HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(
            OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''
        ))),
        2
    );
    IF @ObservedRollbackHash <> @ExpectedRollbackHash
        THROW 51306, 'The reversed procedure hash does not match the reviewed rollback hash.', 1;

    COMMIT TRANSACTION;
    SELECT
        Marker = N'ASTER_OPERATIONS_KPI_CART_SPLIT_ROLLBACK_V1',
        Applied = CONVERT(bit, 1),
        PreRollbackHash = @ObservedCurrentHash,
        RollbackHash = @ObservedRollbackHash;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
