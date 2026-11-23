/* Operations KPI assembly charts: new read-only procedure.

   Creates dbo.usp_QPTS_GetOperationsAssemblyCharts (daily and hourly counts of pieces assembled, N71-6171 bumpers assembled, and
   complete four-piece assembly sets behind the wallboard's assembly charts; no person-level values) and grants the existing
   read-only dashboard login EXECUTE and VIEW DEFINITION on it. No existing object is changed. The bumper and set rules are copied
   unchanged from the reviewed rollup procedure; the procedure reads QPTS and writes nothing but session temp tables. This script is
   hash-gated and reversible (see 2026-11-23-rollback-operations-assembly-charts.sql).
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @ExpectedHash varchar(64) = 'CAFDD61970487B477E441D83847B3AA87205E186AE83105DE6B87289D3C22023';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsAssemblyCharts';

IF OBJECT_ID(@ProcedureName, N'P') IS NOT NULL
    THROW 54391, 'Assembly-chart procedure already exists; refusing to replace it.', 1;
IF DATABASE_PRINCIPAL_ID(N'OperationsKpiRollup_RO') IS NULL
    THROW 54392, 'The read-only dashboard principal OperationsKpiRollup_RO was not found.', 1;

DECLARE @ReviewedDefinition nvarchar(max) = N'/*
    Read-only assembly chart series for the Operations KPI wallboard.

    For the report date and the 13 Sunday-to-Saturday weeks that end with it, returns per day and per clock hour of
    the report date: pieces assembled, N71-6171 bumpers assembled, and complete four-piece N33 / Chassis Fairing
    assembly sets. Everything is dated by the assembly scan (EDI Data Table AssembledDate, plant clock time): a piece
    counts on the day and hour it was scanned assembled; a set counts on the day and hour of the LAST scan among its
    four pieces. Service-model parts are excluded. The bumper and set rules are copied from
    dbo.usp_QPTS_GetOperationsQualityShippingRollup, and complete sets are decided day by day as of the end of each day
    (the way the rollup decides the card for that date), so each day equals the wallboard''s Assembled bumpers and Complete
    assy sets cards for that date. No user, login or other person-level value is returned.

    Result sets: 0 metadata, 1 daily series, 2 hourly series for the report date.
    This procedure does not write to any QPTS data table.
*/
CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsAssemblyCharts
    @ReportDateOverride date = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

    DECLARE @ReportDate date = COALESCE(@ReportDateOverride, DATEADD(day, -1, CONVERT(date, GETDATE())));
    DECLARE @WeekStart date = DATEADD(day, -(DATEDIFF(day, CONVERT(date, ''19000107'', 112), @ReportDate) % 7), @ReportDate);
    DECLARE @ChartStart date = DATEADD(week, -12, @WeekStart);
    DECLARE @ChartStartAt datetime2(0) = CONVERT(datetime2(0), @ChartStart);
    DECLARE @ReportStartAt datetime2(0) = CONVERT(datetime2(0), @ReportDate);
    DECLARE @WindowEndExclusive datetime2(0) = DATEADD(day, 1, @ReportStartAt);

    IF OBJECT_ID(N''tempdb..#AssembledPieces'') IS NOT NULL DROP TABLE #AssembledPieces;
    IF OBJECT_ID(N''tempdb..#SetPieces'') IS NOT NULL DROP TABLE #SetPieces;
    IF OBJECT_ID(N''tempdb..#SetDays'') IS NOT NULL DROP TABLE #SetDays;
    IF OBJECT_ID(N''tempdb..#CompleteSets'') IS NOT NULL DROP TABLE #CompleteSets;

    SELECT
        e.[Part ID] AS part_id,
        e.AssembledDate AS assembled_at,
        CASE WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6171%'' THEN 1 ELSE 0 END AS is_bumper
    INTO #AssembledPieces
    FROM dbo.[EDI Data Table] AS e
    WHERE e.AssembledDate >= @ChartStartAt
      AND e.AssembledDate < @WindowEndExclusive
      AND ISNULL(e.Model, N'''') <> N''Service'';

    -- Every non-service piece of a possible set, whatever its date (a set can span days).
    SELECT
        CONVERT(nvarchar(255), e.[Sequence]) AS sequence_id,
        e.[Part ID] AS part_id,
        e.AssembledDate AS assembled_at
    INTO #SetPieces
    FROM dbo.[EDI Data Table] AS e
    WHERE e.AssembledDate IS NOT NULL
      AND e.AssembledDate < @WindowEndExclusive
      AND ISNULL(e.Model, N'''') <> N''Service''
      AND (
          LEFT(LTRIM(CONVERT(nvarchar(255), e.[Part Number])), 3) = N''N33''
          OR LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Chassis Fairing''
      )
      AND NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), e.[Sequence]))), N'''') IS NOT NULL;

    CREATE CLUSTERED INDEX IX_SetPieces ON #SetPieces (sequence_id, assembled_at);

    -- A set is complete on a day when, counting every piece assembled up to the end of that day, its Sequence has
    -- exactly four distinct Part IDs and one of them was assembled that day: the rollup''s own rule, applied day by day.
    SELECT DISTINCT sequence_id, CONVERT(date, assembled_at) AS day_assembled
    INTO #SetDays
    FROM #SetPieces
    WHERE assembled_at >= @ChartStartAt;

    -- The report date''s sets with the time the last piece was scanned (as of the end of the report date).
    SELECT MAX(assembled_at) AS completed_at
    INTO #CompleteSets
    FROM #SetPieces
    GROUP BY sequence_id
    HAVING COUNT(DISTINCT part_id) = 4;

    SELECT
        N''operations-kpi-assembly-charts-v1'' AS method_version,
        @ReportDate AS report_date,
        @WeekStart AS week_start,
        @ChartStart AS chart_start,
        (SELECT COUNT(*) FROM #AssembledPieces) AS fact_rows;

    SELECT
        days.bucket_start,
        ISNULL(pieces.pieces, 0) AS pieces,
        ISNULL(pieces.bumpers, 0) AS bumpers,
        ISNULL(sets.complete_sets, 0) AS complete_sets
    FROM (
        SELECT TOP (DATEDIFF(day, @ChartStart, @ReportDate) + 1)
            DATEADD(day, ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) - 1, @ChartStart) AS bucket_start
        FROM sys.all_objects
    ) AS days
    LEFT JOIN (
        SELECT
            CONVERT(date, assembled_at) AS bucket_start,
            COUNT(DISTINCT part_id) AS pieces,
            COUNT(DISTINCT CASE WHEN is_bumper = 1 THEN part_id END) AS bumpers
        FROM #AssembledPieces
        GROUP BY CONVERT(date, assembled_at)
    ) AS pieces ON pieces.bucket_start = days.bucket_start
    LEFT JOIN (
        SELECT set_days.day_assembled AS bucket_start, COUNT(*) AS complete_sets
        FROM #SetDays AS set_days
        WHERE (
            SELECT COUNT(DISTINCT set_pieces.part_id)
            FROM #SetPieces AS set_pieces
            WHERE set_pieces.sequence_id = set_days.sequence_id
              AND set_pieces.assembled_at < DATEADD(day, 1, CONVERT(datetime2(0), set_days.day_assembled))
        ) = 4
        GROUP BY set_days.day_assembled
    ) AS sets ON sets.bucket_start = days.bucket_start
    ORDER BY days.bucket_start;

    SELECT
        DATEADD(hour, hours.hour_start, @ReportStartAt) AS bucket_start,
        ISNULL(pieces.pieces, 0) AS pieces,
        ISNULL(pieces.bumpers, 0) AS bumpers,
        ISNULL(sets.complete_sets, 0) AS complete_sets
    FROM (
        SELECT TOP (24) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) - 1 AS hour_start
        FROM sys.all_objects
    ) AS hours
    LEFT JOIN (
        SELECT
            DATEPART(hour, assembled_at) AS hour_start,
            COUNT(DISTINCT part_id) AS pieces,
            COUNT(DISTINCT CASE WHEN is_bumper = 1 THEN part_id END) AS bumpers
        FROM #AssembledPieces
        WHERE assembled_at >= @ReportStartAt
        GROUP BY DATEPART(hour, assembled_at)
    ) AS pieces ON pieces.hour_start = hours.hour_start
    LEFT JOIN (
        SELECT DATEPART(hour, completed_at) AS hour_start, COUNT(*) AS complete_sets
        FROM #CompleteSets
        WHERE completed_at >= @ReportStartAt
        GROUP BY DATEPART(hour, completed_at)
    ) AS sets ON sets.hour_start = hours.hour_start
    ORDER BY hours.hour_start;

    DROP TABLE #CompleteSets;
    DROP TABLE #SetDays;
    DROP TABLE #SetPieces;
    DROP TABLE #AssembledPieces;
END
';
DECLARE @ReviewedHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), @ReviewedDefinition)), 2);
IF @ReviewedHash <> @ExpectedHash
    THROW 54393, 'Assembly-chart migration reviewed-definition hash mismatch.', 1;

BEGIN TRY
    IF @CommitChange = 1
    BEGIN
        BEGIN TRANSACTION;
        EXEC sys.sp_executesql @ReviewedDefinition;
        GRANT EXECUTE ON dbo.usp_QPTS_GetOperationsAssemblyCharts TO [OperationsKpiRollup_RO];
        GRANT VIEW DEFINITION ON dbo.usp_QPTS_GetOperationsAssemblyCharts TO [OperationsKpiRollup_RO];
        DECLARE @AppliedHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
            'SHA2_256',
            CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
        ), 2);
        IF @AppliedHash <> @ExpectedHash
            THROW 54394, 'Assembly-chart migration applied procedure hash mismatch.', 1;
        COMMIT TRANSACTION;
    END;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

DECLARE @FinalHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256',
    CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);
IF @CommitChange = 1 AND @FinalHash <> @ExpectedHash
    THROW 54395, 'Assembly-chart migration final procedure hash mismatch.', 1;

SELECT
    @CommitChange AS commit_change,
    @ReviewedHash AS reviewed_candidate_hash,
    @FinalHash AS final_hash;
