/*
    Read-only process-time rollup for the Operations KPI wallboard.

    For every paint-scope part (Origin F, no Service model) the item history is cut into
    loops. A loop starts at a load_line event (first pass) or a load_line_repaint event
    (repaint) and holds the first booth entry, oven entry, oven exit, end-of-line approval,
    and final approval that follow it before the next loop starts. Each interval is dated
    by the scan that ends it and reported per day as an average, median, and 90th percentile
    in minutes. Intervals that run backwards (scans out of order) are counted in
    excluded_negative and left out of the statistics. Repaint loops are reported separately
    from first-pass loops so repaints never change the standard averages.

    The window is 91 days ending on the report date and never reaches before the governed
    event-history start of 2026-09-08.

    This procedure does not write to QPTS data tables.
*/
CREATE   PROCEDURE dbo.usp_QPTS_GetOperationsProcessTimes
    @ReportDateOverride date = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

    DECLARE @ReportDate date = COALESCE(@ReportDateOverride, CONVERT(date, GETDATE()));
    DECLARE @HistoryStart date = CONVERT(date, '20260908', 112);
    DECLARE @WindowStart date = DATEADD(day, -90, @ReportDate);
    IF @WindowStart < @HistoryStart SET @WindowStart = @HistoryStart;
    DECLARE @EventStart date = DATEADD(day, -21, @WindowStart);
    IF @EventStart < @HistoryStart SET @EventStart = @HistoryStart;
    DECLARE @WindowEndExclusive datetime2(0) = DATEADD(day, 1, CONVERT(datetime2(0), @ReportDate));

    SELECT e.[Part ID] AS part_id
    INTO #ProcessParts
    FROM dbo.[EDI Data Table] AS e
    WHERE e.[Part ID] IS NOT NULL
    GROUP BY e.[Part ID]
    HAVING MAX(CASE WHEN ISNULL(e.Model, N'') = N'Service' THEN 1 ELSE 0 END) = 0
       AND MAX(CASE WHEN CONVERT(nvarchar(8), e.[Origin]) = N'F' THEN 1 ELSE 0 END) = 1;

    CREATE UNIQUE CLUSTERED INDEX IX_ProcessParts_Part ON #ProcessParts(part_id);

    SELECT
        h.id,
        h.part_id,
        CASE CONVERT(nvarchar(80), h.moment_category)
            WHEN N'load_line' THEN N'L'
            WHEN N'load_line_repaint' THEN N'LR'
            WHEN N'paint_booth_entered' THEN N'B'
            WHEN N'paint_oven_entered' THEN N'Oi'
            WHEN N'paint_oven_exited' THEN N'Oo'
            WHEN N'end_of_line_approved' THEN N'EA'
            WHEN N'final_approved' THEN N'F'
        END AS step_code,
        DATEADD(
            millisecond,
            DATEDIFF(millisecond, CONVERT(time(3), '00:00:00'), CAST(h.moment_time AS time(3))),
            CONVERT(datetime2(3), CONVERT(date, h.moment_date))
        ) AS moment_at
    INTO #ProcessEvents
    FROM dbo.ritem_history_new AS h
    INNER JOIN #ProcessParts AS p ON p.part_id = h.part_id
    WHERE h.moment_date >= @EventStart
      AND h.moment_date < @WindowEndExclusive
      AND CONVERT(nvarchar(80), h.moment_category) IN (
          N'load_line',
          N'load_line_repaint',
          N'paint_booth_entered',
          N'paint_oven_entered',
          N'paint_oven_exited',
          N'end_of_line_approved',
          N'final_approved'
      );

    CREATE INDEX IX_ProcessEvents_PartMoment ON #ProcessEvents(part_id, moment_at, id);

    ;WITH Sequenced AS (
        SELECT
            e.id,
            e.part_id,
            e.step_code,
            e.moment_at,
            SUM(CASE WHEN e.step_code IN (N'L', N'LR') THEN 1 ELSE 0 END) OVER (
                PARTITION BY e.part_id
                ORDER BY e.moment_at, e.id
                ROWS UNBOUNDED PRECEDING
            ) AS loop_no
        FROM #ProcessEvents AS e
    )
    SELECT
        s.part_id,
        s.loop_no,
        MAX(CASE WHEN s.step_code = N'LR' THEN 1 ELSE 0 END) AS is_repaint,
        MIN(CASE WHEN s.step_code IN (N'L', N'LR') THEN s.moment_at END) AS loaded_at,
        MIN(CASE WHEN s.step_code = N'B' THEN s.moment_at END) AS booth_at,
        MIN(CASE WHEN s.step_code = N'Oi' THEN s.moment_at END) AS oven_in_at,
        MIN(CASE WHEN s.step_code = N'Oo' THEN s.moment_at END) AS oven_out_at,
        MIN(CASE WHEN s.step_code = N'EA' THEN s.moment_at END) AS eol_approved_at,
        MIN(CASE WHEN s.step_code = N'F' THEN s.moment_at END) AS final_approved_at
    INTO #ProcessLoops
    FROM Sequenced AS s
    WHERE s.loop_no > 0
    GROUP BY s.part_id, s.loop_no;

    SELECT
        CONVERT(date, x.ended_at) AS event_date,
        CASE WHEN l.is_repaint = 1 THEN N'repaint' ELSE N'standard' END AS population,
        x.stage_order,
        x.stage,
        CONVERT(decimal(14, 2), DATEDIFF(second, x.started_at, x.ended_at) / 60.0) AS minutes
    INTO #ProcessIntervals
    FROM #ProcessLoops AS l
    CROSS APPLY (VALUES
        (1, N'load_to_booth', l.loaded_at, l.booth_at),
        (2, N'booth_to_oven_in', l.booth_at, l.oven_in_at),
        (3, N'oven_in_to_oven_out', l.oven_in_at, l.oven_out_at),
        (4, N'oven_out_to_eol_approved', l.oven_out_at, l.eol_approved_at),
        (5, N'eol_approved_to_final_approved', l.eol_approved_at, l.final_approved_at),
        (6, N'total_load_to_final_approved', l.loaded_at, l.final_approved_at)
    ) AS x(stage_order, stage, started_at, ended_at)
    WHERE x.started_at IS NOT NULL
      AND x.ended_at IS NOT NULL
      AND x.ended_at >= CONVERT(datetime2(3), @WindowStart)
      AND x.ended_at < @WindowEndExclusive;

    SELECT
        @ReportDate AS report_date,
        @WindowStart AS window_start,
        @HistoryStart AS history_start,
        N'operations-kpi-process-time-v1' AS method_version,
        (SELECT COUNT_BIG(*) FROM #ProcessEvents) AS events_scanned,
        (SELECT COUNT_BIG(*) FROM #ProcessLoops) AS loops_scanned,
        SYSDATETIME() AS generated_at;

    ;WITH Ranked AS (
        SELECT
            i.event_date,
            i.population,
            i.stage_order,
            i.stage,
            i.minutes,
            CASE WHEN i.minutes >= 0 THEN i.minutes END AS valid_minutes,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY CASE WHEN i.minutes >= 0 THEN i.minutes END) OVER (
                PARTITION BY i.event_date, i.population, i.stage_order
            ) AS median_minutes,
            PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY CASE WHEN i.minutes >= 0 THEN i.minutes END) OVER (
                PARTITION BY i.event_date, i.population, i.stage_order
            ) AS p90_minutes
        FROM #ProcessIntervals AS i
    )
    SELECT
        r.event_date,
        r.population,
        r.stage_order,
        r.stage,
        SUM(CASE WHEN r.minutes >= 0 THEN 1 ELSE 0 END) AS intervals,
        CONVERT(decimal(12, 1), AVG(r.valid_minutes)) AS average_minutes,
        CONVERT(decimal(12, 1), MAX(r.median_minutes)) AS median_minutes,
        CONVERT(decimal(12, 1), MAX(r.p90_minutes)) AS p90_minutes,
        SUM(CASE WHEN r.minutes > 720 THEN 1 ELSE 0 END) AS over_12_hours,
        SUM(CASE WHEN r.minutes < 0 THEN 1 ELSE 0 END) AS excluded_negative
    FROM Ranked AS r
    GROUP BY r.event_date, r.population, r.stage_order, r.stage
    ORDER BY r.population, r.stage_order, r.event_date;

    SELECT
        d.event_date,
        d.population,
        SUM(d.loops_loaded) AS loops_loaded,
        SUM(d.loops_finished) AS loops_finished,
        SUM(d.loops_with_every_scan) AS loops_with_every_scan
    FROM (
        SELECT
            CONVERT(date, l.loaded_at) AS event_date,
            CASE WHEN l.is_repaint = 1 THEN N'repaint' ELSE N'standard' END AS population,
            1 AS loops_loaded,
            0 AS loops_finished,
            0 AS loops_with_every_scan
        FROM #ProcessLoops AS l
        WHERE l.loaded_at >= CONVERT(datetime2(3), @WindowStart) AND l.loaded_at < @WindowEndExclusive
        UNION ALL
        SELECT
            CONVERT(date, l.final_approved_at),
            CASE WHEN l.is_repaint = 1 THEN N'repaint' ELSE N'standard' END,
            0,
            1,
            CASE
                WHEN l.booth_at >= l.loaded_at AND l.oven_in_at >= l.booth_at AND l.oven_out_at >= l.oven_in_at
                 AND l.eol_approved_at >= l.oven_out_at AND l.final_approved_at >= l.eol_approved_at THEN 1
                ELSE 0
            END
        FROM #ProcessLoops AS l
        WHERE l.final_approved_at >= CONVERT(datetime2(3), @WindowStart) AND l.final_approved_at < @WindowEndExclusive
    ) AS d
    GROUP BY d.event_date, d.population
    ORDER BY d.population, d.event_date;

    DROP TABLE #ProcessIntervals;
    DROP TABLE #ProcessLoops;
    DROP TABLE #ProcessEvents;
    DROP TABLE #ProcessParts;
END;
