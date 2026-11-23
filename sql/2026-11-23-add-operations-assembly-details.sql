/* Operations KPI assembly details: new read-only procedure.

   Creates dbo.usp_QPTS_GetOperationsAssemblyDetails (daily counts of pieces and N71-6171 bumpers assembled, by operator login and by
   workstation login, behind the drill-down's assembly tables; operator logins are served only to signed-in viewers) and grants the
   existing read-only dashboard login EXECUTE and VIEW DEFINITION on it. No existing object is changed; the procedure reads QPTS and
   writes nothing but session temp tables. This script is hash-gated and reversible (see 2026-11-23-rollback-operations-assembly-details.sql).
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @ExpectedHash varchar(64) = 'CC5217ADD6A6BDACC4EA0951BAA073F0CD8E5E63E0C8AD514A4B78ED13002097';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsAssemblyDetails';

IF OBJECT_ID(@ProcedureName, N'P') IS NOT NULL
    THROW 54401, 'Assembly-details procedure already exists; refusing to replace it.', 1;
IF DATABASE_PRINCIPAL_ID(N'OperationsKpiRollup_RO') IS NULL
    THROW 54402, 'The read-only dashboard principal OperationsKpiRollup_RO was not found.', 1;

DECLARE @ReviewedDefinition nvarchar(max) = N'/*
    Read-only assembly counts by operator and by workstation for the Operations KPI drill-down.

    For the report date and the 13 Sunday-to-Saturday weeks that end with it, returns per day the number of pieces
    assembled and the number of N71-6171 bumpers assembled, once per operator (EDI Data Table AssembledLogin; a blank
    login is returned as a NULL operator) and once per workstation (GPAssyLogin; a blank value is returned as a NULL
    workstation). A piece counts on the day it was scanned assembled (AssembledDate, plant clock time). Service-model
    parts are excluded, as in the wallboard''s assembly tiles, and days without assembly are not returned. Because it
    returns operator logins, the drill-down serves the operator counts only to signed-in viewers.

    Result sets: 0 metadata, 1 daily counts by operator, 2 daily counts by workstation.
    This procedure does not write to any QPTS data table.
*/
CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsAssemblyDetails
    @ReportDateOverride date = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

    DECLARE @ReportDate date = COALESCE(@ReportDateOverride, DATEADD(day, -1, CONVERT(date, GETDATE())));
    DECLARE @WeekStart date = DATEADD(day, -(DATEDIFF(day, CONVERT(date, ''19000107'', 112), @ReportDate) % 7), @ReportDate);
    DECLARE @ChartStart date = DATEADD(week, -12, @WeekStart);
    DECLARE @ChartStartAt datetime2(0) = CONVERT(datetime2(0), @ChartStart);
    DECLARE @WindowEndExclusive datetime2(0) = DATEADD(day, 1, CONVERT(datetime2(0), @ReportDate));

    IF OBJECT_ID(N''tempdb..#AssemblyScans'') IS NOT NULL DROP TABLE #AssemblyScans;

    SELECT
        e.[Part ID] AS part_id,
        CONVERT(date, e.AssembledDate) AS bucket_start,
        NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(100), e.AssembledLogin))), N'''') AS operator,
        NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(100), e.GPAssyLogin))), N'''') AS workstation,
        CASE WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6171%'' THEN 1 ELSE 0 END AS is_bumper
    INTO #AssemblyScans
    FROM dbo.[EDI Data Table] AS e
    WHERE e.AssembledDate >= @ChartStartAt
      AND e.AssembledDate < @WindowEndExclusive
      AND ISNULL(e.Model, N'''') <> N''Service'';

    SELECT
        N''operations-kpi-assembly-details-v1'' AS method_version,
        @ReportDate AS report_date,
        @WeekStart AS week_start,
        @ChartStart AS chart_start,
        COUNT(*) AS fact_rows,
        ISNULL(SUM(CASE WHEN operator IS NULL THEN 1 ELSE 0 END), 0) AS blank_operator_rows,
        ISNULL(SUM(CASE WHEN workstation IS NULL THEN 1 ELSE 0 END), 0) AS blank_workstation_rows
    FROM #AssemblyScans;

    SELECT
        bucket_start,
        operator,
        COUNT(DISTINCT part_id) AS pieces,
        COUNT(DISTINCT CASE WHEN is_bumper = 1 THEN part_id END) AS bumpers
    FROM #AssemblyScans
    GROUP BY bucket_start, operator
    ORDER BY bucket_start, operator;

    SELECT
        bucket_start,
        workstation,
        COUNT(DISTINCT part_id) AS pieces,
        COUNT(DISTINCT CASE WHEN is_bumper = 1 THEN part_id END) AS bumpers
    FROM #AssemblyScans
    GROUP BY bucket_start, workstation
    ORDER BY bucket_start, workstation;

    DROP TABLE #AssemblyScans;
END
';
DECLARE @ReviewedHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), @ReviewedDefinition)), 2);
IF @ReviewedHash <> @ExpectedHash
    THROW 54403, 'Assembly-details migration reviewed-definition hash mismatch.', 1;

BEGIN TRY
    IF @CommitChange = 1
    BEGIN
        BEGIN TRANSACTION;
        EXEC sys.sp_executesql @ReviewedDefinition;
        GRANT EXECUTE ON dbo.usp_QPTS_GetOperationsAssemblyDetails TO [OperationsKpiRollup_RO];
        GRANT VIEW DEFINITION ON dbo.usp_QPTS_GetOperationsAssemblyDetails TO [OperationsKpiRollup_RO];
        DECLARE @AppliedHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
            'SHA2_256',
            CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
        ), 2);
        IF @AppliedHash <> @ExpectedHash
            THROW 54404, 'Assembly-details migration applied procedure hash mismatch.', 1;
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
    THROW 54405, 'Assembly-details migration final procedure hash mismatch.', 1;

SELECT
    @CommitChange AS commit_change,
    @ReviewedHash AS reviewed_candidate_hash,
    @FinalHash AS final_hash;
