/*
    Add aggregate MIC/Painted assembly detail and a distinct N71-6164 family
    to the Operations KPI rollup without changing existing headline totals.

    Existing Prd fields remain backward-compatible and continue to include
    N71-6164. New N71 subset fields let the renderer display an exclusive Prd
    value by subtraction. Shipping pieces and physical racks use exclusive
    FUKA / Bumpers / N71-6164 / Fairings categories. No part IDs, sequences,
    rack IDs, or other row-level data leave the procedure.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @ExpectedOldHash varchar(64) = '142E3C5764E0E80D4694D085C42DAF82EC153CEBEA757C965BE02B19A61FF373';
DECLARE @ExpectedNewHash varchar(64) = '415953E2A0675AADA2C99A7BABC4F43DBB04B21ACB7BB8D9361AF094C96B7CE3';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @OldDefinition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedOldHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@OldDefinition, N''))), 2);

IF @ObservedOldHash <> @ExpectedOldHash
    THROW 53101, 'Dashboard MIC/N71 pre-change hash mismatch.', 1;

DECLARE @CandidateDefinition nvarchar(max) = @OldDefinition;
DECLARE @CreateHeader nvarchar(256) = N'CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @AlterHeader nvarchar(256) = N'ALTER   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';

IF CHARINDEX(@CreateHeader, @CandidateDefinition) > 0
    SET @CandidateDefinition = REPLACE(@CandidateDefinition, @CreateHeader, @AlterHeader);
ELSE IF CHARINDEX(@AlterHeader, @CandidateDefinition) = 0
    THROW 53102, 'Dashboard procedure header is not in the reviewed shape.', 1;

DECLARE @OldPartClass nvarchar(max) = N'        MAX(classified.is_paint_scope) AS is_paint_scope,
        MAX(classified.is_repaint_classified) AS is_repaint_classified
    INTO #PartClass
    FROM (
        SELECT
            e.[Part ID] AS part_id,
            CASE WHEN ISNULL(e.Model, N'''') = N''Service'' THEN 1 ELSE 0 END AS is_service,
            CASE
                WHEN LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) = N''N33''
                  OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6171%'' THEN 1 ELSE 0
            END AS is_bv,
            CASE
                WHEN CONVERT(nvarchar(8), e.[Origin]) = N''F'' OR ISNULL(e.Model, N'''') = N''Service'' THEN 1 ELSE 0
            END AS is_paint_scope,';
DECLARE @NewPartClass nvarchar(max) = N'        MAX(classified.is_paint_scope) AS is_paint_scope,
        MAX(classified.is_n71_6164) AS is_n71_6164,
        MAX(classified.is_repaint_classified) AS is_repaint_classified
    INTO #PartClass
    FROM (
        SELECT
            e.[Part ID] AS part_id,
            CASE WHEN ISNULL(e.Model, N'''') = N''Service'' THEN 1 ELSE 0 END AS is_service,
            CASE
                WHEN LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) = N''N33''
                  OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6171%'' THEN 1 ELSE 0
            END AS is_bv,
            CASE
                WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6164%'' THEN 1 ELSE 0
            END AS is_n71_6164,
            CASE
                WHEN CONVERT(nvarchar(8), e.[Origin]) = N''F'' OR ISNULL(e.Model, N'''') = N''Service'' THEN 1 ELSE 0
            END AS is_paint_scope,';

DECLARE @OldEvents nvarchar(max) = N'    /* Materialize classified event grains once for the historical rollup. */
    SELECT
        h.moment_date AS report_date,
        h.part_id,
        h.PaintCart_ID,
        h.moment_at,
        pc.part_class
    INTO #PaintExitEvents
    FROM #HistoryAll AS h
    INNER JOIN #PartClass AS pc ON pc.part_id = h.part_id
    WHERE h.moment_category = N''paint_oven_exited''
      AND h.PaintCart_ID IS NOT NULL
      AND h.PaintCart_ID > 0
      AND pc.is_paint_scope = 1;

    CREATE INDEX IX_RollupPaintExitEvents_DateCart ON #PaintExitEvents(report_date, PaintCart_ID);

    SELECT
        report_date,
        PaintCart_ID,
        CASE
            WHEN MAX(CASE WHEN part_class = N''Svc'' THEN 1 ELSE 0 END) = 1 THEN N''Svc''
            WHEN MAX(CASE WHEN part_class = N''BV'' THEN 1 ELSE 0 END) = 1 THEN N''BV''
            ELSE N''Prd''
        END AS cart_class
    INTO #PaintCartClasses
    FROM #PaintExitEvents
    GROUP BY report_date, PaintCart_ID;

    CREATE UNIQUE CLUSTERED INDEX IX_RollupPaintCartClasses_DateCart ON #PaintCartClasses(report_date, PaintCart_ID);

    SELECT
        h.moment_date AS report_date,
        h.part_id,
        h.PaintCart_ID,
        pc.part_class
    INTO #LoadedEvents
    FROM #HistoryAll AS h
    INNER JOIN #PartClass AS pc ON pc.part_id = h.part_id
    WHERE h.moment_category IN (N''load_line'', N''load_line_repaint'');

    CREATE INDEX IX_RollupLoadedEvents_DateCart ON #LoadedEvents(report_date, PaintCart_ID);

    SELECT
        report_date,
        PaintCart_ID,
        CASE
            WHEN MAX(CASE WHEN part_class = N''Svc'' THEN 1 ELSE 0 END) = 1 THEN N''Svc''
            WHEN MAX(CASE WHEN part_class = N''BV'' THEN 1 ELSE 0 END) = 1 THEN N''BV''
            ELSE N''Prd''
        END AS cart_class
    INTO #LoadedCartClasses
    FROM #LoadedEvents
    WHERE PaintCart_ID IS NOT NULL
    GROUP BY report_date, PaintCart_ID;';
DECLARE @NewEvents nvarchar(max) = N'    /* Materialize classified event grains once for the historical rollup. */
    SELECT
        h.moment_date AS report_date,
        h.part_id,
        h.PaintCart_ID,
        h.moment_at,
        pc.part_class,
        pc.is_n71_6164
    INTO #PaintExitEvents
    FROM #HistoryAll AS h
    INNER JOIN #PartClass AS pc ON pc.part_id = h.part_id
    WHERE h.moment_category = N''paint_oven_exited''
      AND h.PaintCart_ID IS NOT NULL
      AND h.PaintCart_ID > 0
      AND pc.is_paint_scope = 1;

    CREATE INDEX IX_RollupPaintExitEvents_DateCart ON #PaintExitEvents(report_date, PaintCart_ID);

    SELECT
        report_date,
        PaintCart_ID,
        CASE
            WHEN MAX(CASE WHEN part_class = N''Svc'' THEN 1 ELSE 0 END) = 1 THEN N''Svc''
            WHEN MAX(CASE WHEN part_class = N''BV'' THEN 1 ELSE 0 END) = 1 THEN N''BV''
            ELSE N''Prd''
        END AS cart_class,
        CASE
            WHEN MAX(CASE WHEN part_class = N''Svc'' THEN 1 ELSE 0 END) = 0
             AND MAX(CASE WHEN part_class = N''BV'' THEN 1 ELSE 0 END) = 0
             AND MAX(is_n71_6164) = 1 THEN 1 ELSE 0
        END AS is_n71_6164_cart
    INTO #PaintCartClasses
    FROM #PaintExitEvents
    GROUP BY report_date, PaintCart_ID;

    CREATE UNIQUE CLUSTERED INDEX IX_RollupPaintCartClasses_DateCart ON #PaintCartClasses(report_date, PaintCart_ID);

    SELECT
        h.moment_date AS report_date,
        h.part_id,
        h.PaintCart_ID,
        pc.part_class,
        pc.is_n71_6164
    INTO #LoadedEvents
    FROM #HistoryAll AS h
    INNER JOIN #PartClass AS pc ON pc.part_id = h.part_id
    WHERE h.moment_category IN (N''load_line'', N''load_line_repaint'');

    CREATE INDEX IX_RollupLoadedEvents_DateCart ON #LoadedEvents(report_date, PaintCart_ID);

    SELECT
        report_date,
        PaintCart_ID,
        CASE
            WHEN MAX(CASE WHEN part_class = N''Svc'' THEN 1 ELSE 0 END) = 1 THEN N''Svc''
            WHEN MAX(CASE WHEN part_class = N''BV'' THEN 1 ELSE 0 END) = 1 THEN N''BV''
            ELSE N''Prd''
        END AS cart_class,
        CASE
            WHEN MAX(CASE WHEN part_class = N''Svc'' THEN 1 ELSE 0 END) = 0
             AND MAX(CASE WHEN part_class = N''BV'' THEN 1 ELSE 0 END) = 0
             AND MAX(is_n71_6164) = 1 THEN 1 ELSE 0
        END AS is_n71_6164_cart
    INTO #LoadedCartClasses
    FROM #LoadedEvents
    WHERE PaintCart_ID IS NOT NULL
    GROUP BY report_date, PaintCart_ID;';

DECLARE @OldPaintExitDaily nvarchar(max) = N'            COUNT(DISTINCT CASE WHEN pc.cart_class = N''Prd'' THEN pe.PaintCart_ID END) AS production_paint_carts,
            COUNT(DISTINCT CASE WHEN pc.cart_class = N''BV'' THEN pe.PaintCart_ID END) AS bv_paint_carts,
            COUNT(DISTINCT CASE WHEN pc.cart_class = N''Svc'' THEN pe.PaintCart_ID END) AS service_paint_carts,
            COUNT(*) AS paint_pieces_processed,
            SUM(CASE WHEN pe.part_class = N''Prd'' THEN 1 ELSE 0 END) AS production_paint_pieces_processed,
            SUM(CASE WHEN pe.part_class = N''BV'' THEN 1 ELSE 0 END) AS bv_paint_pieces_processed,
            SUM(CASE WHEN pe.part_class = N''Svc'' THEN 1 ELSE 0 END) AS service_paint_pieces_processed,';
DECLARE @NewPaintExitDaily nvarchar(max) = N'            COUNT(DISTINCT CASE WHEN pc.cart_class = N''Prd'' THEN pe.PaintCart_ID END) AS production_paint_carts,
            COUNT(DISTINCT CASE WHEN pc.cart_class = N''BV'' THEN pe.PaintCart_ID END) AS bv_paint_carts,
            COUNT(DISTINCT CASE WHEN pc.cart_class = N''Svc'' THEN pe.PaintCart_ID END) AS service_paint_carts,
            COUNT(DISTINCT CASE WHEN pc.cart_class = N''Prd'' AND pc.is_n71_6164_cart = 1 THEN pe.PaintCart_ID END) AS n71_6164_paint_carts,
            COUNT(*) AS paint_pieces_processed,
            SUM(CASE WHEN pe.part_class = N''Prd'' THEN 1 ELSE 0 END) AS production_paint_pieces_processed,
            SUM(CASE WHEN pe.part_class = N''BV'' THEN 1 ELSE 0 END) AS bv_paint_pieces_processed,
            SUM(CASE WHEN pe.part_class = N''Svc'' THEN 1 ELSE 0 END) AS service_paint_pieces_processed,
            SUM(CASE WHEN pe.part_class = N''Prd'' AND pe.is_n71_6164 = 1 THEN 1 ELSE 0 END) AS n71_6164_paint_pieces_processed,';

DECLARE @OldLoadedDaily nvarchar(max) = N'            SUM(CASE WHEN le.part_class = N''Prd'' THEN 1 ELSE 0 END) AS production_parts_loaded,
            SUM(CASE WHEN le.part_class = N''BV'' THEN 1 ELSE 0 END) AS bv_parts_loaded,
            SUM(CASE WHEN le.part_class = N''Svc'' THEN 1 ELSE 0 END) AS service_parts_loaded,
            COUNT(DISTINCT le.part_id) AS unique_pieces_loaded,
            COUNT(DISTINCT le.PaintCart_ID) AS carts_loaded,
            COUNT(DISTINCT CASE WHEN lc.cart_class = N''Prd'' THEN le.PaintCart_ID END) AS production_carts_loaded,
            COUNT(DISTINCT CASE WHEN lc.cart_class = N''BV'' THEN le.PaintCart_ID END) AS bv_carts_loaded,
            COUNT(DISTINCT CASE WHEN lc.cart_class = N''Svc'' THEN le.PaintCart_ID END) AS service_carts_loaded';
DECLARE @NewLoadedDaily nvarchar(max) = N'            SUM(CASE WHEN le.part_class = N''Prd'' THEN 1 ELSE 0 END) AS production_parts_loaded,
            SUM(CASE WHEN le.part_class = N''BV'' THEN 1 ELSE 0 END) AS bv_parts_loaded,
            SUM(CASE WHEN le.part_class = N''Svc'' THEN 1 ELSE 0 END) AS service_parts_loaded,
            SUM(CASE WHEN le.part_class = N''Prd'' AND le.is_n71_6164 = 1 THEN 1 ELSE 0 END) AS n71_6164_parts_loaded,
            COUNT(DISTINCT le.part_id) AS unique_pieces_loaded,
            COUNT(DISTINCT le.PaintCart_ID) AS carts_loaded,
            COUNT(DISTINCT CASE WHEN lc.cart_class = N''Prd'' THEN le.PaintCart_ID END) AS production_carts_loaded,
            COUNT(DISTINCT CASE WHEN lc.cart_class = N''BV'' THEN le.PaintCart_ID END) AS bv_carts_loaded,
            COUNT(DISTINCT CASE WHEN lc.cart_class = N''Svc'' THEN le.PaintCart_ID END) AS service_carts_loaded,
            COUNT(DISTINCT CASE WHEN lc.cart_class = N''Prd'' AND lc.is_n71_6164_cart = 1 THEN le.PaintCart_ID END) AS n71_6164_carts_loaded';

DECLARE @OldAssembly nvarchar(max) = N'    ), AssemblyDaily AS (
        SELECT
            assembled.report_date,
            COUNT(DISTINCT assembled.part_id) AS parts_assembled,
            COUNT(DISTINCT CASE WHEN assembled.is_bumper = 1 THEN assembled.part_id END) AS assembled_bumper_count
        FROM (
            SELECT
                CONVERT(date, e.AssembledDate) AS report_date,
                e.[Part ID] AS part_id,
                CASE WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6171%'' THEN 1 ELSE 0 END AS is_bumper
            FROM dbo.[EDI Data Table] AS e
            WHERE e.AssembledDate >= CONVERT(datetime2(0), @HistoryStart)
              AND e.AssembledDate < @WindowEndExclusive
              AND ISNULL(e.Model, N'''') <> N''Service''
              AND LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) IN (N''N33'', N''N35'', N''N71'')
        ) AS assembled
        GROUP BY assembled.report_date
    ), CompleteAssemblyDaily AS (
        SELECT
            complete_sets.report_date,
            COUNT(*) AS complete_assy_sets
        FROM (
            SELECT
                MAX(CONVERT(date, e.AssembledDate)) AS report_date,
                CONVERT(nvarchar(255), e.[Sequence]) AS sequence_id
            FROM dbo.[EDI Data Table] AS e
            WHERE e.AssembledDate IS NOT NULL
              AND e.AssembledDate < @WindowEndExclusive
              AND ISNULL(e.Model, N'''') <> N''Service''
              AND (
                  LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) = N''N33''
                  OR LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Chassis Fairing''
              )
              AND NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), e.[Sequence]))), N'''') IS NOT NULL
            GROUP BY CONVERT(nvarchar(255), e.[Sequence])
            HAVING COUNT(DISTINCT e.[Part ID]) = 4
        ) AS complete_sets
        WHERE complete_sets.report_date >= @HistoryStart
        GROUP BY complete_sets.report_date
    ), ReceivingQuantityDaily AS (';
DECLARE @NewAssembly nvarchar(max) = N'    ), AssemblyDaily AS (
        SELECT
            assembled.report_date,
            COUNT(DISTINCT assembled.part_id) AS parts_assembled,
            COUNT(DISTINCT CASE WHEN assembled.is_bumper = 1 THEN assembled.part_id END) AS assembled_bumper_count,
            COUNT(DISTINCT CASE WHEN assembled.is_bumper = 1 AND assembled.is_mic = 1 THEN assembled.part_id END) AS mic_assembled_bumper_count,
            COUNT(DISTINCT CASE WHEN assembled.is_bumper = 1 AND assembled.is_mic = 0 THEN assembled.part_id END) AS painted_assembled_bumper_count
        FROM (
            SELECT
                CONVERT(date, e.AssembledDate) AS report_date,
                e.[Part ID] AS part_id,
                CASE WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6171%'' THEN 1 ELSE 0 END AS is_bumper,
                CASE WHEN UPPER(LTRIM(RTRIM(CONVERT(nvarchar(255), e.Color)))) = N''MIC'' THEN 1 ELSE 0 END AS is_mic
            FROM dbo.[EDI Data Table] AS e
            WHERE e.AssembledDate >= CONVERT(datetime2(0), @HistoryStart)
              AND e.AssembledDate < @WindowEndExclusive
              AND ISNULL(e.Model, N'''') <> N''Service''
              AND LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) IN (N''N33'', N''N35'', N''N71'')
        ) AS assembled
        GROUP BY assembled.report_date
    ), CompleteAssemblyDaily AS (
        SELECT
            complete_sets.report_date,
            COUNT(*) AS complete_assy_sets,
            SUM(complete_sets.is_mic_set) AS mic_complete_assy_sets,
            SUM(1 - complete_sets.is_mic_set) AS painted_complete_assy_sets
        FROM (
            SELECT
                MAX(CONVERT(date, e.AssembledDate)) AS report_date,
                CONVERT(nvarchar(255), e.[Sequence]) AS sequence_id,
                CASE WHEN COUNT(DISTINCT CASE
                    WHEN UPPER(LTRIM(RTRIM(CONVERT(nvarchar(255), e.Color)))) = N''MIC'' THEN e.[Part ID]
                END) = 4 THEN 1 ELSE 0 END AS is_mic_set
            FROM dbo.[EDI Data Table] AS e
            WHERE e.AssembledDate IS NOT NULL
              AND e.AssembledDate < @WindowEndExclusive
              AND ISNULL(e.Model, N'''') <> N''Service''
              AND (
                  LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) = N''N33''
                  OR LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Chassis Fairing''
              )
              AND NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), e.[Sequence]))), N'''') IS NOT NULL
            GROUP BY CONVERT(nvarchar(255), e.[Sequence])
            HAVING COUNT(DISTINCT e.[Part ID]) = 4
        ) AS complete_sets
        WHERE complete_sets.report_date >= @HistoryStart
        GROUP BY complete_sets.report_date
    ), ReceivingQuantityDaily AS (';

DECLARE @OldRack nvarchar(max) = N'    ), RackContents AS (
        SELECT
            CONVERT(date, e.ship_date) AS report_date,
            LTRIM(RTRIM(CONVERT(nvarchar(255), e.Rack))) AS rack_id,
            SUM(CASE
                WHEN CONVERT(nvarchar(10), e.Origin) = N''B'' THEN 0
                WHEN CONVERT(nvarchar(10), e.Origin) = N''F''
                 AND (LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71%''
                   OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N33%'') THEN 0
                ELSE 1
            END) AS fuka_parts,
            SUM(CASE WHEN CONVERT(nvarchar(10), e.Origin) = N''B'' THEN 1 ELSE 0 END) AS bumper_parts,
            SUM(CASE
                WHEN CONVERT(nvarchar(10), e.Origin) = N''F''
                 AND (LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71%''
                   OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N33%'') THEN 1
                ELSE 0
            END) AS fairing_parts
        FROM dbo.[EDI Data Table] AS e
        WHERE e.ship_date >= CONVERT(datetime2(0), @HistoryStart)
          AND e.ship_date < @WindowEndExclusive
          AND CONVERT(nvarchar(255), e.ship_status) = N''SHIPPED''
          AND ISNULL(e.Model, N'''') <> N''Service''
          AND NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), e.Rack))), N'''') IS NOT NULL
        GROUP BY CONVERT(date, e.ship_date), LTRIM(RTRIM(CONVERT(nvarchar(255), e.Rack)))
    ), RackClasses AS (
        SELECT
            report_date,
            rack_id,
            CASE
                WHEN fuka_parts >= bumper_parts AND fuka_parts >= fairing_parts AND fuka_parts > 0 THEN N''FUKA''
                WHEN bumper_parts >= fairing_parts AND bumper_parts > 0 THEN N''Bumpers''
                WHEN fairing_parts > 0 THEN N''Fairings''
                ELSE N''Other''
            END AS rack_type
        FROM RackContents
    ), RackDaily AS (
        SELECT
            report_date,
            COUNT(*) AS racks_shipped,
            SUM(CASE WHEN rack_type = N''FUKA'' THEN 1 ELSE 0 END) AS fuka_racks_shipped,
            SUM(CASE WHEN rack_type = N''Bumpers'' THEN 1 ELSE 0 END) AS bumper_racks_shipped,
            SUM(CASE WHEN rack_type = N''Fairings'' THEN 1 ELSE 0 END) AS fairing_racks_shipped,
            SUM(CASE WHEN rack_type = N''Other'' THEN 1 ELSE 0 END) AS other_racks_shipped
        FROM RackClasses
        GROUP BY report_date
    )';
DECLARE @NewRack nvarchar(max) = N'    ), RackContents AS (
        SELECT
            CONVERT(date, e.ship_date) AS report_date,
            LTRIM(RTRIM(CONVERT(nvarchar(255), e.Rack))) AS rack_id,
            SUM(CASE WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6164%'' THEN 1 ELSE 0 END) AS n71_6164_parts,
            SUM(CASE
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
            END) AS fairing_parts
        FROM dbo.[EDI Data Table] AS e
        WHERE e.ship_date >= CONVERT(datetime2(0), @HistoryStart)
          AND e.ship_date < @WindowEndExclusive
          AND CONVERT(nvarchar(255), e.ship_status) = N''SHIPPED''
          AND ISNULL(e.Model, N'''') <> N''Service''
          AND NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), e.Rack))), N'''') IS NOT NULL
        GROUP BY CONVERT(date, e.ship_date), LTRIM(RTRIM(CONVERT(nvarchar(255), e.Rack)))
    ), RackClasses AS (
        SELECT
            report_date,
            rack_id,
            CASE
                WHEN n71_6164_parts >= fuka_parts AND n71_6164_parts >= bumper_parts AND n71_6164_parts >= fairing_parts AND n71_6164_parts > 0 THEN N''N71-6164''
                WHEN fuka_parts >= bumper_parts AND fuka_parts >= fairing_parts AND fuka_parts > 0 THEN N''FUKA''
                WHEN bumper_parts >= fairing_parts AND bumper_parts > 0 THEN N''Bumpers''
                WHEN fairing_parts > 0 THEN N''Fairings''
                ELSE N''Other''
            END AS rack_type
        FROM RackContents
    ), RackDaily AS (
        SELECT
            report_date,
            COUNT(*) AS racks_shipped,
            SUM(CASE WHEN rack_type = N''FUKA'' THEN 1 ELSE 0 END) AS fuka_racks_shipped,
            SUM(CASE WHEN rack_type = N''Bumpers'' THEN 1 ELSE 0 END) AS bumper_racks_shipped,
            SUM(CASE WHEN rack_type = N''N71-6164'' THEN 1 ELSE 0 END) AS n71_6164_racks_shipped,
            SUM(CASE WHEN rack_type = N''Fairings'' THEN 1 ELSE 0 END) AS fairing_racks_shipped,
            SUM(CASE WHEN rack_type = N''Other'' THEN 1 ELSE 0 END) AS other_racks_shipped
        FROM RackClasses
        GROUP BY report_date
    )';

DECLARE @OldDailyCore nvarchar(max) = N'        COALESCE(l.service_parts_loaded, 0) AS service_parts_loaded,
        COALESCE(l.unique_pieces_loaded, 0) AS unique_pieces_loaded,
        COALESCE(l.carts_loaded, 0) AS carts_loaded,
        COALESCE(l.production_carts_loaded, 0) AS production_carts_loaded,
        COALESCE(l.bv_carts_loaded, 0) AS bv_carts_loaded,
        COALESCE(l.service_carts_loaded, 0) AS service_carts_loaded,
        COALESCE(px.paint_processed, 0) AS paint_processed,
        COALESCE(px.production_paint_carts, 0) AS production_paint_carts,
        COALESCE(px.bv_paint_carts, 0) AS bv_paint_carts,
        COALESCE(px.service_paint_carts, 0) AS service_paint_carts,
        COALESCE(px.paint_pieces_processed, 0) AS paint_pieces_processed,
        COALESCE(px.production_paint_pieces_processed, 0) AS production_paint_pieces_processed,
        COALESCE(px.bv_paint_pieces_processed, 0) AS bv_paint_pieces_processed,
        COALESCE(px.service_paint_pieces_processed, 0) AS service_paint_pieces_processed,
        COALESCE(px.unique_pieces_processed, 0) AS unique_pieces_processed,';
DECLARE @NewDailyCore nvarchar(max) = N'        COALESCE(l.service_parts_loaded, 0) AS service_parts_loaded,
        COALESCE(l.n71_6164_parts_loaded, 0) AS n71_6164_parts_loaded,
        COALESCE(l.unique_pieces_loaded, 0) AS unique_pieces_loaded,
        COALESCE(l.carts_loaded, 0) AS carts_loaded,
        COALESCE(l.production_carts_loaded, 0) AS production_carts_loaded,
        COALESCE(l.bv_carts_loaded, 0) AS bv_carts_loaded,
        COALESCE(l.service_carts_loaded, 0) AS service_carts_loaded,
        COALESCE(l.n71_6164_carts_loaded, 0) AS n71_6164_carts_loaded,
        COALESCE(px.paint_processed, 0) AS paint_processed,
        COALESCE(px.production_paint_carts, 0) AS production_paint_carts,
        COALESCE(px.bv_paint_carts, 0) AS bv_paint_carts,
        COALESCE(px.service_paint_carts, 0) AS service_paint_carts,
        COALESCE(px.n71_6164_paint_carts, 0) AS n71_6164_paint_carts,
        COALESCE(px.paint_pieces_processed, 0) AS paint_pieces_processed,
        COALESCE(px.production_paint_pieces_processed, 0) AS production_paint_pieces_processed,
        COALESCE(px.bv_paint_pieces_processed, 0) AS bv_paint_pieces_processed,
        COALESCE(px.service_paint_pieces_processed, 0) AS service_paint_pieces_processed,
        COALESCE(px.n71_6164_paint_pieces_processed, 0) AS n71_6164_paint_pieces_processed,
        COALESCE(px.unique_pieces_processed, 0) AS unique_pieces_processed,';

DECLARE @OldDailyAssembly nvarchar(max) = N'        COALESCE(ca.complete_assy_sets, 0) AS complete_assy_sets,
        COALESCE(a.assembled_bumper_count, 0) AS assembled_bumper_count,';
DECLARE @NewDailyAssembly nvarchar(max) = N'        COALESCE(ca.complete_assy_sets, 0) AS complete_assy_sets,
        COALESCE(ca.mic_complete_assy_sets, 0) AS mic_complete_assy_sets,
        COALESCE(ca.painted_complete_assy_sets, 0) AS painted_complete_assy_sets,
        COALESCE(a.assembled_bumper_count, 0) AS assembled_bumper_count,
        COALESCE(a.mic_assembled_bumper_count, 0) AS mic_assembled_bumper_count,
        COALESCE(a.painted_assembled_bumper_count, 0) AS painted_assembled_bumper_count,';

DECLARE @OldDailyRack nvarchar(max) = N'        COALESCE(rd.bumper_racks_shipped, 0) AS bumper_racks_shipped,
        COALESCE(rd.fairing_racks_shipped, 0) AS fairing_racks_shipped,';
DECLARE @NewDailyRack nvarchar(max) = N'        COALESCE(rd.bumper_racks_shipped, 0) AS bumper_racks_shipped,
        COALESCE(rd.n71_6164_racks_shipped, 0) AS n71_6164_racks_shipped,
        COALESCE(rd.fairing_racks_shipped, 0) AS fairing_racks_shipped,';

DECLARE @OldPeriodCore nvarchar(max) = N'        COALESCE(SUM(d.service_parts_loaded), 0) AS service_parts_loaded,
        COALESCE(SUM(d.unique_pieces_loaded), 0) AS unique_pieces_loaded,
        COALESCE(SUM(d.carts_loaded), 0) AS carts_loaded,
        COALESCE(SUM(d.production_carts_loaded), 0) AS production_carts_loaded,
        COALESCE(SUM(d.bv_carts_loaded), 0) AS bv_carts_loaded,
        COALESCE(SUM(d.service_carts_loaded), 0) AS service_carts_loaded,
        COALESCE(SUM(d.paint_processed), 0) AS paint_processed,
        COALESCE(SUM(d.production_paint_carts), 0) AS production_paint_carts,
        COALESCE(SUM(d.bv_paint_carts), 0) AS bv_paint_carts,
        COALESCE(SUM(d.service_paint_carts), 0) AS service_paint_carts,
        COALESCE(SUM(d.paint_pieces_processed), 0) AS paint_pieces_processed,
        COALESCE(SUM(d.production_paint_pieces_processed), 0) AS production_paint_pieces_processed,
        COALESCE(SUM(d.bv_paint_pieces_processed), 0) AS bv_paint_pieces_processed,
        COALESCE(SUM(d.service_paint_pieces_processed), 0) AS service_paint_pieces_processed,
        COALESCE(SUM(d.unique_pieces_processed), 0) AS unique_pieces_processed,';
DECLARE @NewPeriodCore nvarchar(max) = N'        COALESCE(SUM(d.service_parts_loaded), 0) AS service_parts_loaded,
        COALESCE(SUM(d.n71_6164_parts_loaded), 0) AS n71_6164_parts_loaded,
        COALESCE(SUM(d.unique_pieces_loaded), 0) AS unique_pieces_loaded,
        COALESCE(SUM(d.carts_loaded), 0) AS carts_loaded,
        COALESCE(SUM(d.production_carts_loaded), 0) AS production_carts_loaded,
        COALESCE(SUM(d.bv_carts_loaded), 0) AS bv_carts_loaded,
        COALESCE(SUM(d.service_carts_loaded), 0) AS service_carts_loaded,
        COALESCE(SUM(d.n71_6164_carts_loaded), 0) AS n71_6164_carts_loaded,
        COALESCE(SUM(d.paint_processed), 0) AS paint_processed,
        COALESCE(SUM(d.production_paint_carts), 0) AS production_paint_carts,
        COALESCE(SUM(d.bv_paint_carts), 0) AS bv_paint_carts,
        COALESCE(SUM(d.service_paint_carts), 0) AS service_paint_carts,
        COALESCE(SUM(d.n71_6164_paint_carts), 0) AS n71_6164_paint_carts,
        COALESCE(SUM(d.paint_pieces_processed), 0) AS paint_pieces_processed,
        COALESCE(SUM(d.production_paint_pieces_processed), 0) AS production_paint_pieces_processed,
        COALESCE(SUM(d.bv_paint_pieces_processed), 0) AS bv_paint_pieces_processed,
        COALESCE(SUM(d.service_paint_pieces_processed), 0) AS service_paint_pieces_processed,
        COALESCE(SUM(d.n71_6164_paint_pieces_processed), 0) AS n71_6164_paint_pieces_processed,
        COALESCE(SUM(d.unique_pieces_processed), 0) AS unique_pieces_processed,';

DECLARE @OldPeriodAssembly nvarchar(max) = N'        COALESCE(SUM(d.complete_assy_sets), 0) AS complete_assy_sets,
        COALESCE(SUM(d.assembled_bumper_count), 0) AS assembled_bumper_count,';
DECLARE @NewPeriodAssembly nvarchar(max) = N'        COALESCE(SUM(d.complete_assy_sets), 0) AS complete_assy_sets,
        COALESCE(SUM(d.mic_complete_assy_sets), 0) AS mic_complete_assy_sets,
        COALESCE(SUM(d.painted_complete_assy_sets), 0) AS painted_complete_assy_sets,
        COALESCE(SUM(d.assembled_bumper_count), 0) AS assembled_bumper_count,
        COALESCE(SUM(d.mic_assembled_bumper_count), 0) AS mic_assembled_bumper_count,
        COALESCE(SUM(d.painted_assembled_bumper_count), 0) AS painted_assembled_bumper_count,';

DECLARE @OldPeriodRack nvarchar(max) = N'        COALESCE(SUM(d.bumper_racks_shipped), 0) AS bumper_racks_shipped,
        COALESCE(SUM(d.fairing_racks_shipped), 0) AS fairing_racks_shipped,';
DECLARE @NewPeriodRack nvarchar(max) = N'        COALESCE(SUM(d.bumper_racks_shipped), 0) AS bumper_racks_shipped,
        COALESCE(SUM(d.n71_6164_racks_shipped), 0) AS n71_6164_racks_shipped,
        COALESCE(SUM(d.fairing_racks_shipped), 0) AS fairing_racks_shipped,';

DECLARE @OldShippingCase nvarchar(max) = N'        CASE
            WHEN CONVERT(nvarchar(10), e.Origin) = N''B'' THEN N''Bumpers''
            WHEN CONVERT(nvarchar(10), e.Origin) = N''F'' AND (LTRIM(e.[Part Number]) LIKE N''N71%'' OR LTRIM(e.[Part Number]) LIKE N''N33%'') THEN N''Chassis Fairings''
            ELSE N''Fenders''
        END';
DECLARE @NewShippingCase nvarchar(max) = N'        CASE
            WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6164%'' THEN N''N71-6164''
            WHEN CONVERT(nvarchar(10), e.Origin) = N''B'' THEN N''Bumpers''
            WHEN CONVERT(nvarchar(10), e.Origin) = N''F'' AND (LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71%'' OR LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N33%'') THEN N''Fairings''
            ELSE N''FUKA''
        END';

IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @OldPartClass, N''))) / LEN(@OldPartClass) <> 1
   OR (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @OldEvents, N''))) / LEN(@OldEvents) <> 1
   OR (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @OldPaintExitDaily, N''))) / LEN(@OldPaintExitDaily) <> 1
   OR (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @OldLoadedDaily, N''))) / LEN(@OldLoadedDaily) <> 1
   OR (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @OldAssembly, N''))) / LEN(@OldAssembly) <> 1
   OR (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @OldRack, N''))) / LEN(@OldRack) <> 1
   OR (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @OldDailyCore, N''))) / LEN(@OldDailyCore) <> 1
   OR (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @OldDailyAssembly, N''))) / LEN(@OldDailyAssembly) <> 1
   OR (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @OldDailyRack, N''))) / LEN(@OldDailyRack) <> 1
   OR (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @OldPeriodCore, N''))) / LEN(@OldPeriodCore) <> 1
   OR (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @OldPeriodAssembly, N''))) / LEN(@OldPeriodAssembly) <> 1
   OR (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @OldPeriodRack, N''))) / LEN(@OldPeriodRack) <> 1
   OR (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @OldShippingCase, N''))) / LEN(@OldShippingCase) <> 2
    THROW 53103, 'Dashboard MIC/N71 migration markers are not unique.', 1;

SET @CandidateDefinition = REPLACE(@CandidateDefinition, @OldPartClass, @NewPartClass);
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @OldEvents, @NewEvents);
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @OldPaintExitDaily, @NewPaintExitDaily);
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @OldLoadedDaily, @NewLoadedDaily);
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @OldAssembly, @NewAssembly);
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @OldRack, @NewRack);
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @OldDailyCore, @NewDailyCore);
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @OldDailyAssembly, @NewDailyAssembly);
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @OldDailyRack, @NewDailyRack);
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @OldPeriodCore, @NewPeriodCore);
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @OldPeriodAssembly, @NewPeriodAssembly);
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @OldPeriodRack, @NewPeriodRack);
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @OldShippingCase, @NewShippingCase);

IF CHARINDEX(N'n71_6164_parts_loaded', @CandidateDefinition) = 0
   OR CHARINDEX(N'n71_6164_paint_pieces_processed', @CandidateDefinition) = 0
   OR CHARINDEX(N'mic_complete_assy_sets', @CandidateDefinition) = 0
   OR CHARINDEX(N'painted_complete_assy_sets', @CandidateDefinition) = 0
   OR CHARINDEX(N'mic_assembled_bumper_count', @CandidateDefinition) = 0
   OR CHARINDEX(N'painted_assembled_bumper_count', @CandidateDefinition) = 0
   OR CHARINDEX(N'n71_6164_racks_shipped', @CandidateDefinition) = 0
    THROW 53104, 'Dashboard MIC/N71 candidate is incomplete.', 1;

BEGIN TRANSACTION;
EXEC sys.sp_executesql @CandidateDefinition;

DECLARE @CandidateHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256',
    CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);

IF @ExpectedNewHash IS NOT NULL AND @CandidateHash <> @ExpectedNewHash
    THROW 53105, 'Dashboard MIC/N71 candidate hash mismatch.', 1;

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
    THROW 53106, 'Dashboard MIC/N71 final hash is inconsistent with commit mode.', 1;

SELECT
    Marker = N'ASTER_OPERATIONS_KPI_MIC_N71_BREAKDOWNS_V1',
    Applied = @CommitChange,
    OldDefinitionSHA256 = @ObservedOldHash,
    CandidateDefinitionSHA256 = @CandidateHash,
    FinalDefinitionSHA256 = @FinalHash;
