/* Rollback for 2026-11-19-add-operations-person-roster.sql: drops dbo.usp_QPTS_GetOperationsPersonRoster.

   Refuses to run unless the live procedure is exactly the reviewed definition, so a later edit is never
   dropped silently. Its grants disappear with it. No other object is touched.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @ExpectedHash varchar(64) = '0EACA9821E82112D9C93DD21A4CBE78B49D5F2A8E2DAF197AD40BA07BFD2E159';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsPersonRoster';

IF OBJECT_ID(@ProcedureName, N'P') IS NULL
    THROW 54386, 'Roster procedure is not present; nothing to roll back.', 1;
DECLARE @ObservedHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256',
    CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);
IF @ObservedHash <> @ExpectedHash
    THROW 54387, 'Roster procedure differs from the reviewed definition; refusing to drop it.', 1;

BEGIN TRY
    IF @CommitChange = 1
    BEGIN
        BEGIN TRANSACTION;
        DROP PROCEDURE dbo.usp_QPTS_GetOperationsPersonRoster;
        IF OBJECT_ID(@ProcedureName, N'P') IS NOT NULL
            THROW 54388, 'Roster procedure still exists after the drop.', 1;
        COMMIT TRANSACTION;
    END;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

SELECT
    @CommitChange AS commit_change,
    @ObservedHash AS observed_hash,
    CASE WHEN OBJECT_ID(@ProcedureName, N'P') IS NULL THEN 1 ELSE 0 END AS procedure_absent;
