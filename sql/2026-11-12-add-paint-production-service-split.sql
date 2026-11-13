/*
    Hash-gated extension of the approved Operations KPI rollup.

    The production migration was first executed in rollback-only preview mode.
    The exact candidate and rollback hashes from that preview are pinned here.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @ExpectedOldHash varchar(64) = 'A733058BF6F816A07D9D6249BC0B1BCCC00EFA26ECEA1F98A0390E682AA9AB88';
DECLARE @ExpectedNewHash varchar(64) = '7A2992FA73CC9BF282148A2179789E651141057A1225475A5C1360C0C655083E';
DECLARE @ExpectedRollbackHash varchar(64) = 'A733058BF6F816A07D9D6249BC0B1BCCC00EFA26ECEA1F98A0390E682AA9AB88';
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
    THROW 51400, 'The approved Operations KPI rollup procedure is absent.', 1;
IF @ObservedOldHash <> @ExpectedOldHash
    THROW 51401, 'The Operations KPI rollup procedure does not match the reviewed pre-change hash.', 1;

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
    THROW 51402, 'Expected exactly one CREATE PROCEDURE marker.', 1;
IF (LEN(@Definition) - LEN(REPLACE(@Definition, @OldPaintExit, N''))) / LEN(@OldPaintExit) <> 1
    THROW 51403, 'Expected exactly one reviewed PaintExitDaily block.', 1;
IF (LEN(@Definition) - LEN(REPLACE(@Definition, @OldDailySelect, N''))) / LEN(@OldDailySelect) <> 1
    THROW 51404, 'Expected exactly one reviewed daily paint projection.', 1;
IF (LEN(@Definition) - LEN(REPLACE(@Definition, @OldPeriodSelect, N''))) / LEN(@OldPeriodSelect) <> 1
    THROW 51405, 'Expected exactly one reviewed period paint projection.', 1;

SET @Definition = REPLACE(@Definition, @OldCreate, @NewCreate);
SET @Definition = REPLACE(@Definition, @OldPaintExit, @NewPaintExit);
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
        THROW 51406, 'The applied procedure hash does not match the reviewed candidate hash.', 1;
    IF @StoredDefinition NOT LIKE N'%production_paint_carts%'
       OR @StoredDefinition NOT LIKE N'%service_paint_carts%'
       OR @StoredDefinition NOT LIKE N'%production_paint_pieces_processed%'
       OR @StoredDefinition NOT LIKE N'%service_paint_pieces_processed%'
        THROW 51407, 'The applied procedure is missing the approved paint split.', 1;

    DECLARE @RollbackDefinition nvarchar(max) = @StoredDefinition;
    SET @RollbackDefinition = REPLACE(@RollbackDefinition, @NewPaintExit, @OldPaintExit);
    SET @RollbackDefinition = REPLACE(@RollbackDefinition, @NewDailySelect, @OldDailySelect);
    SET @RollbackDefinition = REPLACE(@RollbackDefinition, @NewPeriodSelect, @OldPeriodSelect);
    SET @RollbackHash = CONVERT(
        varchar(64),
        HASHBYTES('SHA2_256', CONVERT(varbinary(max), @RollbackDefinition)),
        2
    );

    IF @ExpectedRollbackHash IS NOT NULL AND @RollbackHash <> @ExpectedRollbackHash
        THROW 51408, 'The calculated rollback hash does not match the reviewed rollback hash.', 1;

    IF @CommitChange = 1
        COMMIT TRANSACTION;
    ELSE
        ROLLBACK TRANSACTION;

    SELECT
        Marker = N'ASTER_OPERATIONS_KPI_PAINT_SPLIT_V1',
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
