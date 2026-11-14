/*
    Add aggregate shipped physical-rack counts by line set while preserving
    the existing trailers_prepared metric and every KPI formula.

    A rack is grouped by EDI Data Table.Rack on its ship date and counted
    once. Mixed racks are assigned to their dominant line set using the same
    deterministic tie order as trailers: FUKA, then Bumpers, then Fairings.
    No rack identifiers or part-level rows leave the procedure.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitChange bit = 1;
DECLARE @ExpectedOldHash varchar(64) = '80689CEC1019830F14445EB5AE5B4CBE35A9CFFB7494688BB12D8481413B0C7A';
DECLARE @ExpectedNewHash varchar(64) = '142E3C5764E0E80D4694D085C42DAF82EC153CEBEA757C965BE02B19A61FF373';
DECLARE @ProcedureName nvarchar(256) = N'dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @OldDefinition nvarchar(max) = OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P'));
DECLARE @ObservedOldHash varchar(64) = CONVERT(varchar(64), HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(@OldDefinition, N''))), 2);

IF @ObservedOldHash <> @ExpectedOldHash
    THROW 53001, 'Dashboard shipped-rack pre-change hash mismatch.', 1;

DECLARE @CandidateDefinition nvarchar(max) = @OldDefinition;
DECLARE @CreateHeader nvarchar(256) = N'CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';
DECLARE @AlterHeader nvarchar(256) = N'ALTER   PROCEDURE dbo.usp_QPTS_GetOperationsQualityShippingRollup';

IF CHARINDEX(@CreateHeader, @CandidateDefinition) > 0
    SET @CandidateDefinition = REPLACE(@CandidateDefinition, @CreateHeader, @AlterHeader);
ELSE IF CHARINDEX(@AlterHeader, @CandidateDefinition) = 0
    THROW 53002, 'Dashboard procedure header is not in the reviewed shape.', 1;

DECLARE @CteToken nvarchar(max) = N'        FROM TrailerClasses
        GROUP BY report_date
    )
    SELECT';
DECLARE @CteReplacement nvarchar(max) = N'        FROM TrailerClasses
        GROUP BY report_date
    ), RackContents AS (
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
    )
    SELECT';

IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @CteToken, N''))) / LEN(@CteToken) <> 1
    THROW 53003, 'Dashboard shipped-rack CTE marker is not unique.', 1;
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @CteToken, @CteReplacement);

DECLARE @DailyToken nvarchar(max) = N'        COALESCE(td.other_trailers_prepared, 0) AS other_trailers_prepared,
        s0.pieces_scheduled,';
DECLARE @DailyReplacement nvarchar(max) = N'        COALESCE(td.other_trailers_prepared, 0) AS other_trailers_prepared,
        COALESCE(rd.racks_shipped, 0) AS racks_shipped,
        COALESCE(rd.fuka_racks_shipped, 0) AS fuka_racks_shipped,
        COALESCE(rd.bumper_racks_shipped, 0) AS bumper_racks_shipped,
        COALESCE(rd.fairing_racks_shipped, 0) AS fairing_racks_shipped,
        COALESCE(rd.other_racks_shipped, 0) AS other_racks_shipped,
        s0.pieces_scheduled,';

IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @DailyToken, N''))) / LEN(@DailyToken) <> 1
    THROW 53004, 'Dashboard shipped-rack daily marker is not unique.', 1;
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @DailyToken, @DailyReplacement);

DECLARE @JoinToken nvarchar(max) = N'    LEFT JOIN TrailerDaily AS td ON td.report_date = d.report_date
    LEFT JOIN ScheduleDaily AS s0 ON s0.report_date = d.report_date';
DECLARE @JoinReplacement nvarchar(max) = N'    LEFT JOIN TrailerDaily AS td ON td.report_date = d.report_date
    LEFT JOIN RackDaily AS rd ON rd.report_date = d.report_date
    LEFT JOIN ScheduleDaily AS s0 ON s0.report_date = d.report_date';

IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @JoinToken, N''))) / LEN(@JoinToken) <> 1
    THROW 53005, 'Dashboard shipped-rack join marker is not unique.', 1;
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @JoinToken, @JoinReplacement);

DECLARE @PeriodToken nvarchar(max) = N'        COALESCE(SUM(d.other_trailers_prepared), 0) AS other_trailers_prepared,
        COALESCE(SUM(d.pieces_scheduled), 0) AS pieces_scheduled,';
DECLARE @PeriodReplacement nvarchar(max) = N'        COALESCE(SUM(d.other_trailers_prepared), 0) AS other_trailers_prepared,
        COALESCE(SUM(d.racks_shipped), 0) AS racks_shipped,
        COALESCE(SUM(d.fuka_racks_shipped), 0) AS fuka_racks_shipped,
        COALESCE(SUM(d.bumper_racks_shipped), 0) AS bumper_racks_shipped,
        COALESCE(SUM(d.fairing_racks_shipped), 0) AS fairing_racks_shipped,
        COALESCE(SUM(d.other_racks_shipped), 0) AS other_racks_shipped,
        COALESCE(SUM(d.pieces_scheduled), 0) AS pieces_scheduled,';

IF (LEN(@CandidateDefinition) - LEN(REPLACE(@CandidateDefinition, @PeriodToken, N''))) / LEN(@PeriodToken) <> 1
    THROW 53006, 'Dashboard shipped-rack period marker is not unique.', 1;
SET @CandidateDefinition = REPLACE(@CandidateDefinition, @PeriodToken, @PeriodReplacement);

IF CHARINDEX(N'RackContents AS', @CandidateDefinition) = 0
   OR CHARINDEX(N'racks_shipped', @CandidateDefinition) = 0
   OR CHARINDEX(N'fuka_racks_shipped', @CandidateDefinition) = 0
   OR CHARINDEX(N'bumper_racks_shipped', @CandidateDefinition) = 0
   OR CHARINDEX(N'fairing_racks_shipped', @CandidateDefinition) = 0
   OR CHARINDEX(N'other_racks_shipped', @CandidateDefinition) = 0
    THROW 53007, 'Dashboard shipped-rack candidate is incomplete.', 1;

BEGIN TRANSACTION;
EXEC sys.sp_executesql @CandidateDefinition;

DECLARE @CandidateHash varchar(64) = CONVERT(varchar(64), HASHBYTES(
    'SHA2_256',
    CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION(OBJECT_ID(@ProcedureName, N'P')), N''))
), 2);

IF @ExpectedNewHash IS NOT NULL AND @CandidateHash <> @ExpectedNewHash
    THROW 53008, 'Dashboard shipped-rack candidate hash mismatch.', 1;

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
    THROW 53009, 'Dashboard shipped-rack final hash is inconsistent with commit mode.', 1;

SELECT
    Marker = N'ASTER_OPERATIONS_KPI_SHIPPED_RACK_COUNTS_V1',
    Applied = @CommitChange,
    OldDefinitionSHA256 = @ObservedOldHash,
    CandidateDefinitionSHA256 = @CandidateHash,
    FinalDefinitionSHA256 = @FinalHash;
