/* Operations KPI signed-in names view: new read-only roster procedure.

   Creates dbo.usp_QPTS_GetOperationsPersonRoster (employee ID and name on file from dbo.tblPaintBoothEmployees) and grants the existing
   read-only dashboard login EXECUTE and VIEW DEFINITION on it. No existing object is changed. The procedure
   reads QPTS and writes nothing. This script is hash-gated and reversible (see
   2026-11-19-rollback-operations-person-roster.sql).
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @ExpectedHash varchar(64) = '0EACA9821E82112D9C93DD21A4CBE78B49D5F2A8E2DAF197AD40BA07BFD2E159';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsPersonRoster';

IF OBJECT_ID(@ProcedureName, N'P') IS NOT NULL
    THROW 54381, 'Roster procedure already exists; refusing to replace it.', 1;
IF DATABASE_PRINCIPAL_ID(N'OperationsKpiRollup_RO') IS NULL
    THROW 54382, 'The read-only dashboard principal OperationsKpiRollup_RO was not found.', 1;

DECLARE @ReviewedDefinition nvarchar(max) = N'/*
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
        NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(200), pe.PainterName))), N'''') AS display_name
    FROM dbo.tblPaintBoothEmployees AS pe
    WHERE pe.EmployeeID IS NOT NULL
      AND NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(200), pe.PainterName))), N'''') IS NOT NULL
    ORDER BY CONVERT(nvarchar(32), pe.EmployeeID);
END;
';
DECLARE @ReviewedHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), @ReviewedDefinition)), 2);
IF @ReviewedHash <> @ExpectedHash
    THROW 54383, 'Roster migration reviewed-definition hash mismatch.', 1;

BEGIN TRY
    IF @CommitChange = 1
    BEGIN
        BEGIN TRANSACTION;
        EXEC sys.sp_executesql @ReviewedDefinition;
        GRANT EXECUTE ON dbo.usp_QPTS_GetOperationsPersonRoster TO [OperationsKpiRollup_RO];
        GRANT VIEW DEFINITION ON dbo.usp_QPTS_GetOperationsPersonRoster TO [OperationsKpiRollup_RO];
        DECLARE @AppliedHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
            'SHA2_256',
            CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
        ), 2);
        IF @AppliedHash <> @ExpectedHash
            THROW 54384, 'Roster migration applied procedure hash mismatch.', 1;
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
    THROW 54385, 'Roster migration final procedure hash mismatch.', 1;

SELECT
    @CommitChange AS commit_change,
    @ReviewedHash AS reviewed_candidate_hash,
    @FinalHash AS final_hash;
