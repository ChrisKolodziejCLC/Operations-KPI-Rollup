/* Reverse only the reviewed 2026-11-12 paint production/service split. */
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @ExpectedCurrentHash varchar(64) = '7A2992FA73CC9BF282148A2179789E651141057A1225475A5C1360C0C655083E';
DECLARE @ExpectedRollbackHash varchar(64) = 'A733058BF6F816A07D9D6249BC0B1BCCC00EFA26ECEA1F98A0390E682AA9AB88';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @LF nchar(1) = NCHAR(10);
DECLARE @Definition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedCurrentHash varchar(64) = CONVERT(
    varchar(64),
    HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@Definition, N''))),
    2
);

IF @Definition IS NULL
    THROW 51500, 'The approved Operations KPI rollup procedure is absent.', 1;
IF @ObservedCurrentHash <> @ExpectedCurrentHash
    THROW 51501, 'The Operations KPI rollup procedure does not match the reviewed paint-split hash.', 1;

DECLARE @OldCreate nvarchar(max) = N'CREATE   PROCEDURE';
DECLARE @NewCreate nvarchar(max) = N'ALTER   PROCEDURE';

DECLARE @OldPaintExit nvarchar(max) =
    N'), PaintExitDaily AS (' + @LF +
    N'        SELECT' + @LF +
    N'            h.moment_date AS report_date,' + @LF +
    N'            COUNT(DISTINCT h.PaintCart_ID) AS paint_processed,' + @LF +
    N'            COUNT(*) AS paint_pieces_processed,' + @LF +
    N'            COUNT(DISTINCT DATEPART(hour, h.moment_at)) AS paint_hours' + @LF +
    N'        FROM #HistoryAll AS h' + @LF +
    N'        INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = h.part_id' + @LF +
    N'        WHERE h.moment_category = N''paint_oven_exited''' + @LF +
    N'          AND h.PaintCart_ID IS NOT NULL' + @LF +
    N'          AND h.PaintCart_ID > 0' + @LF +
    N'          AND (CONVERT(nvarchar(8), e.[Origin]) = N''F'' OR ISNULL(e.Model, N'''') = N''Service'')' + @LF +
    N'        GROUP BY h.moment_date';

DECLARE @NewPaintExit nvarchar(max) =
    N'), PaintExitDaily AS (' + @LF +
    N'        SELECT' + @LF +
    N'            h.moment_date AS report_date,' + @LF +
    N'            COUNT(DISTINCT h.PaintCart_ID) AS paint_processed,' + @LF +
    N'            COUNT(DISTINCT CASE WHEN ISNULL(e.Model, N'''') = N''Service'' THEN NULL ELSE h.PaintCart_ID END) AS production_paint_carts,' + @LF +
    N'            COUNT(DISTINCT CASE WHEN ISNULL(e.Model, N'''') = N''Service'' THEN h.PaintCart_ID END) AS service_paint_carts,' + @LF +
    N'            COUNT(*) AS paint_pieces_processed,' + @LF +
    N'            SUM(CASE WHEN ISNULL(e.Model, N'''') = N''Service'' THEN 0 ELSE 1 END) AS production_paint_pieces_processed,' + @LF +
    N'            SUM(CASE WHEN ISNULL(e.Model, N'''') = N''Service'' THEN 1 ELSE 0 END) AS service_paint_pieces_processed,' + @LF +
    N'            COUNT(DISTINCT DATEPART(hour, h.moment_at)) AS paint_hours' + @LF +
    N'        FROM #HistoryAll AS h' + @LF +
    N'        INNER JOIN dbo.[EDI Data Table] AS e ON e.[Part ID] = h.part_id' + @LF +
    N'        WHERE h.moment_category = N''paint_oven_exited''' + @LF +
    N'          AND h.PaintCart_ID IS NOT NULL' + @LF +
    N'          AND h.PaintCart_ID > 0' + @LF +
    N'          AND (CONVERT(nvarchar(8), e.[Origin]) = N''F'' OR ISNULL(e.Model, N'''') = N''Service'')' + @LF +
    N'        GROUP BY h.moment_date';

DECLARE @OldDailySelect nvarchar(max) =
    N'        COALESCE(px.paint_processed, 0) AS paint_processed,' + @LF +
    N'        COALESCE(px.paint_pieces_processed, 0) AS paint_pieces_processed,';

DECLARE @NewDailySelect nvarchar(max) =
    N'        COALESCE(px.paint_processed, 0) AS paint_processed,' + @LF +
    N'        COALESCE(px.production_paint_carts, 0) AS production_paint_carts,' + @LF +
    N'        COALESCE(px.service_paint_carts, 0) AS service_paint_carts,' + @LF +
    N'        COALESCE(px.paint_pieces_processed, 0) AS paint_pieces_processed,' + @LF +
    N'        COALESCE(px.production_paint_pieces_processed, 0) AS production_paint_pieces_processed,' + @LF +
    N'        COALESCE(px.service_paint_pieces_processed, 0) AS service_paint_pieces_processed,';

DECLARE @OldPeriodSelect nvarchar(max) =
    N'        COALESCE(SUM(d.paint_processed), 0) AS paint_processed,' + @LF +
    N'        COALESCE(SUM(d.paint_pieces_processed), 0) AS paint_pieces_processed,';

DECLARE @NewPeriodSelect nvarchar(max) =
    N'        COALESCE(SUM(d.paint_processed), 0) AS paint_processed,' + @LF +
    N'        COALESCE(SUM(d.production_paint_carts), 0) AS production_paint_carts,' + @LF +
    N'        COALESCE(SUM(d.service_paint_carts), 0) AS service_paint_carts,' + @LF +
    N'        COALESCE(SUM(d.paint_pieces_processed), 0) AS paint_pieces_processed,' + @LF +
    N'        COALESCE(SUM(d.production_paint_pieces_processed), 0) AS production_paint_pieces_processed,' + @LF +
    N'        COALESCE(SUM(d.service_paint_pieces_processed), 0) AS service_paint_pieces_processed,';

IF (LEN(@Definition) - LEN(REPLACE(@Definition, @OldCreate, N''))) / LEN(@OldCreate) <> 1
    THROW 51502, 'Expected exactly one CREATE PROCEDURE marker.', 1;
IF (LEN(@Definition) - LEN(REPLACE(@Definition, @NewPaintExit, N''))) / LEN(@NewPaintExit) <> 1
    THROW 51503, 'Expected exactly one reviewed paint-split PaintExitDaily block.', 1;
IF (LEN(@Definition) - LEN(REPLACE(@Definition, @NewDailySelect, N''))) / LEN(@NewDailySelect) <> 1
    THROW 51504, 'Expected exactly one reviewed paint-split daily projection.', 1;
IF (LEN(@Definition) - LEN(REPLACE(@Definition, @NewPeriodSelect, N''))) / LEN(@NewPeriodSelect) <> 1
    THROW 51505, 'Expected exactly one reviewed paint-split period projection.', 1;

SET @Definition = REPLACE(@Definition, @OldCreate, @NewCreate);
SET @Definition = REPLACE(@Definition, @NewPaintExit, @OldPaintExit);
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
        THROW 51506, 'The reversed procedure hash does not match the reviewed rollback hash.', 1;

    COMMIT TRANSACTION;
    SELECT
        Marker = N'ASTER_OPERATIONS_KPI_PAINT_SPLIT_ROLLBACK_V1',
        Applied = CONVERT(bit, 1),
        PreRollbackHash = @ObservedCurrentHash,
        RollbackHash = @ObservedRollbackHash;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
