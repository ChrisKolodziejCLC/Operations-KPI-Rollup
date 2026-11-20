/*
    Read-only person roster for the signed-in names view of the Operations KPI drill-down.

    Returns the paint-booth employee ID and the name on file for every employee that has a name. The drill-down
    shows IDs only; names are looked up on demand, only for an allowlisted Windows sign-in, only for the IDs on
    screen, and are held in memory for ten minutes at most. This procedure writes nothing.
*/
CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsPersonRoster
AS
BEGIN
    SET NOCOUNT ON;
    SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

    SELECT
        CONVERT(nvarchar(32), pe.EmployeeID) AS person_id,
        NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(200), pe.PainterName))), N'') AS display_name
    FROM dbo.tblPaintBoothEmployees AS pe
    WHERE pe.EmployeeID IS NOT NULL
      AND NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(200), pe.PainterName))), N'') IS NOT NULL
    ORDER BY CONVERT(nvarchar(32), pe.EmployeeID);
END;
