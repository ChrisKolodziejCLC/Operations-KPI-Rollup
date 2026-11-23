/*
    Read-only assembly counts by operator and by workstation for the Operations KPI drill-down.

    For the report date and the 13 Sunday-to-Saturday weeks that end with it, returns per day the number of pieces
    assembled and the number of N71-6171 bumpers assembled, once per operator (EDI Data Table AssembledLogin; a blank
    login is returned as a NULL operator) and once per workstation (GPAssyLogin; a blank value is returned as a NULL
    workstation). A piece counts on the day it was scanned assembled (AssembledDate, plant clock time). Service-model
    parts are excluded, as in the wallboard's assembly tiles, and days without assembly are not returned. Because it
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
    DECLARE @WeekStart date = DATEADD(day, -(DATEDIFF(day, CONVERT(date, '19000107', 112), @ReportDate) % 7), @ReportDate);
    DECLARE @ChartStart date = DATEADD(week, -12, @WeekStart);
    DECLARE @ChartStartAt datetime2(0) = CONVERT(datetime2(0), @ChartStart);
    DECLARE @WindowEndExclusive datetime2(0) = DATEADD(day, 1, CONVERT(datetime2(0), @ReportDate));

    IF OBJECT_ID(N'tempdb..#AssemblyScans') IS NOT NULL DROP TABLE #AssemblyScans;

    SELECT
        e.[Part ID] AS part_id,
        CONVERT(date, e.AssembledDate) AS bucket_start,
        NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(100), e.AssembledLogin))), N'') AS operator,
        NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(100), e.GPAssyLogin))), N'') AS workstation,
        CASE WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N'N71-6171%' THEN 1 ELSE 0 END AS is_bumper
    INTO #AssemblyScans
    FROM dbo.[EDI Data Table] AS e
    WHERE e.AssembledDate >= @ChartStartAt
      AND e.AssembledDate < @WindowEndExclusive
      AND ISNULL(e.Model, N'') <> N'Service';

    SELECT
        N'operations-kpi-assembly-details-v1' AS method_version,
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
