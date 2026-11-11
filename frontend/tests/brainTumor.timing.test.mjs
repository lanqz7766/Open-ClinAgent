import assert from "node:assert/strict"
import test from "node:test"
import { normalizeScanDate, normalizeRelativeDay, annotateVisitTiming, visitTimingLabel, visitTimeLabel, visitTimeDetail, visitDisplayLabel, visitIntervalValues, timelineScale, timelineTicks } from "../src/pages/analysis/brainTumor.timing.ts"
import { hitTestTrend, layoutVisitLabels } from "../src/pages/analysis/brainTumor.chartLayout.ts"

test("trend proximity follows actual lines, not the visit's full time column", () => {
  const curves=[[{x:20,y:100},{x:120,y:100}],[{x:20,y:20},{x:120,y:20}]]
  assert.equal(hitTestTrend({x:20,y:60},curves),null)
  assert.equal(hitTestTrend({x:70,y:50},curves),null)
  assert.equal(hitTestTrend({x:70,y:107},curves),null)
  assert.deepEqual(hitTestTrend({x:70,y:105},curves),{index:0,seriesIndex:0})
  assert.deepEqual(hitTestTrend({x:110,y:20},curves),{index:1,seriesIndex:1})
  assert.deepEqual(hitTestTrend({x:125,y:100},curves),{index:1,seriesIndex:0})
})

test("nearby timepoints and vertical segments are resolved by spatial proximity", () => {
  const curves=[[{x:100,y:180},{x:104,y:30},{x:250,y:70}]]
  assert.deepEqual(hitTestTrend({x:104,y:30},curves),{index:1,seriesIndex:0})
  assert.deepEqual(hitTestTrend({x:100,y:178},curves),{index:0,seriesIndex:0})
  assert.equal(hitTestTrend({x:100,y:90},[[{x:100,y:180},{x:100,y:30}]]).index,1)
  assert.equal(hitTestTrend({x:120,y:90},curves),null)
})

test("measured labels never overlap or leave bounds across responsive plot widths", () => {
  for (const positions of [[0,63/389,67/389,199/389,275/389,1],[0,0.01,0.02,0.03,0.04,1],[0,0.5,0.5,1],[0.5,0.5]]) {
    for (const width of [180,240,400,620,1000]) {
      for (const textWidth of [60,92]) {
        const labels=layoutVisitLabels(positions,positions.map(()=>textWidth),0,width)
        assert.equal(labels.length,positions.length)
        labels.forEach((label,i)=>{
          assert.equal(label.anchorX,positions[i]*width)
          assert.ok(label.x-label.width/2>=-0.001)
          assert.ok(label.x+label.width/2<=width+0.001)
          for(const other of labels.slice(i+1)) if(label.lane===other.lane) assert.ok(Math.abs(other.x-label.x)>=(label.width+other.width)/2+15.9)
        })
      }
    }
  }
})

test("nearby visits spread their labels in one row while measurement anchors remain four days apart", () => {
  const positions=[0,63/389,67/389,199/389,275/389,1]
  const labels=layoutVisitLabels(positions,positions.map(()=>60),52,704,[8,712])
  assert.ok(labels.every(label=>label.lane===0))
  assert.ok(labels[1].x<labels[1].anchorX)
  assert.ok(labels[2].x>labels[2].anchorX)
  assert.ok(Math.abs((labels[2].anchorX-labels[1].anchorX)/652-4/389)<1e-10)
  assert.deepEqual(layoutVisitLabels([],[],0,600),[])
})

const point = (id, dateLabel, extra = {}) => ({ id, dateLabel, ...extra })
test("interval presentation distinguishes unknown, first, same-day and selected reference states", () => {
  assert.deepEqual(visitIntervalValues({}), {previous:"Unknown",reference:"Unknown"})
  assert.deepEqual(visitIntervalValues({firstVisit:true,isReference:true}), {previous:"First visit",reference:"Selected reference"})
  assert.deepEqual(visitIntervalValues({intervalDays:0,daysFromReference:0}), {previous:"0 days",reference:"Same day"})
  assert.deepEqual(visitIntervalValues({intervalDays:1,daysFromReference:-1}), {previous:"1 day",reference:"1 day before"})
  assert.equal(visitIntervalValues({daysFromReference:56.40625}).reference, "56.4 days after")
  assert.deepEqual(visitIntervalValues({timingSamePatient:false,intervalDays:5,daysFromReference:5,isReference:true}), {previous:"Unavailable",reference:"Unavailable"})
})

test("changing the reference updates its offset but not adjacent intervals or actual time positions", () => {
  const input = [0,40,140].map((relativeDay,i) => point(String(i),`Visit ${i+1}`,{relativeDay,relativeDayOrigin:"first scan"}))
  const before = annotateVisitTiming(input, "0"), after = annotateVisitTiming(input, "2")
  assert.deepEqual(before.map(p => p.intervalDays), after.map(p => p.intervalDays))
  assert.deepEqual(timelineScale(before).positions, timelineScale(after).positions)
  assert.equal(visitIntervalValues(before[1]).reference,"40 days after")
  assert.equal(visitIntervalValues(after[1]).reference,"100 days before")
})
test("accepts full ISO or DICOM calendar dates and rejects guesses and invalid dates", () => {
  assert.equal(normalizeScanDate("20240229"), "2024-02-29")
  for (const value of [undefined, null, "", "2023-02-29", "2024-02-30", "2024-13-01", "2024-00-01", "2024-01", "Visit 2024-01-01", "2024-0101", "2024-01-01T23:00:00Z"]) assert.equal(normalizeScanDate(value), null)
})
test("sorts dated visits stably and computes previous-visit intervals across leap day and years", () => {
  const input = [point("c", "2024-03-01"), point("a", "2023-12-31"), point("b", "2024-02-29"), point("d", "2024-03-01")]
  const rows = annotateVisitTiming(input, "b")
  assert.deepEqual(rows.map(p => p.id), ["a", "b", "c", "d"])
  assert.deepEqual(rows.map(p => p.intervalDays), [null, 60, 1, 0])
  assert.deepEqual(rows.map(p => p.daysFromReference), [-60, 0, 1, 1])
  assert.equal(input[0].id, "c")
  assert.match(visitTimingLabel(rows[0]), /First visit/)
  assert.match(visitTimingLabel(rows[3]), /0 days/)
})
test("missing dates retain supplied order and never bridge over an unknown visit", () => {
  const rows = annotateVisitTiming([point("a", "2024-01-01"), point("b", "Visit 2"), point("c", "2024-03-01"), point("d", "2024-03-02")], "a")
  assert.deepEqual(rows.map(p => p.intervalDays), [null, null, null, 1])
  assert.equal(rows[1].scanDate, null)
  assert.match(visitTimingLabel(rows[2]), /unavailable/)
})
test("out-of-order dates with unknown position are unavailable rather than clamped to zero", () => {
  const rows = annotateVisitTiming([point("a", "2024-03-01"), point("b", "2024-01-01"), point("c", "Unknown")], "a")
  assert.deepEqual(rows.map(p => p.id), ["a", "b", "c"])
  assert.equal(rows[1].intervalDays, null)
})
test("explicit unavailable provenance blocks dateLabel fallback and cohorts have no intervals", () => {
  const rows = annotateVisitTiming([point("a", "2024-01-01", { scanDate: null }), point("b", "2024-01-02")], "a")
  assert.equal(rows[0].scanDate, null)
  assert.equal(rows[1].intervalDays, null)
  const cohort = annotateVisitTiming([point("b", "2024-02-01"), point("a", "2024-01-01")], "a", false)
  assert.deepEqual(cohort.map(p => p.id), ["b", "a"])
  assert.ok(cohort.every(p => p.intervalDays === null && p.daysFromReference === null))
  assert.match(visitTimingLabel(cohort[0]), /different patients/)
})

test("date axis uses actual elapsed days rather than visit index", () => {
  const rows = annotateVisitTiming([point("a", "2024-01-01"), point("b", "2024-01-11"), point("c", "2024-04-10")], "a")
  assert.equal(timelineScale(rows).mode, "date")
  assert.deepEqual(timelineScale(rows).positions, [0, 0.1, 1])
  assert.ok(timelineTicks(rows).every(t => /^2024-/.test(t.label)))
})

test("relative time retains clinical-table precision and an explicit shared origin", () => {
  const input = [56.40625, 0, 100].map((day, index) => point(String(index), `Visit ${index}`, { scanDate: null, relativeDay: day, relativeDayOrigin: "first scan" }))
  const rows = annotateVisitTiming(input, "0")
  assert.deepEqual(rows.map(r => r.relativeDay), [0, 56.40625, 100])
  assert.deepEqual(rows.map(r => r.scanDate), [null, null, null])
  assert.equal(timelineScale(rows).mode, "day")
  assert.deepEqual(timelineScale(rows).positions, [0, 0.5640625, 1])
  assert.equal(rows[0].daysFromReference, -56.40625)
  assert.equal(rows[1].intervalDays, 56.40625)
  assert.equal(visitTimeLabel(rows[1]), "Day 56.4")
  assert.match(visitTimeDetail(rows[1]), /first scan/)
  assert.match(visitTimingLabel(rows[1]), /56.4 days/)
  assert.equal(visitTimeLabel(point("z", "", {scanDate:"2024-01-01", relativeDay:12})), "2024-01-01")
})

test("unknown, conflicting origins and cross-patient series do not imply elapsed time", () => {
  const rows = annotateVisitTiming([point("a", "Visit 1", {relativeDay:0,relativeDayOrigin:"diagnosis"}), point("b", "Visit 2", {relativeDay:10,relativeDayOrigin:"first scan"})], "a")
  assert.equal(timelineScale(rows).mode, "ordinal")
  assert.equal(rows[1].intervalDays, null)
  const missing = annotateVisitTiming([point("a","Day 1"),point("b","Day 9")], "a")
  assert.equal(timelineScale(missing).mode, "ordinal")
  assert.match(timelineScale(missing).label, /timing unavailable/)
  assert.equal(timelineScale([{scanDate:"2024-01-01"},{scanDate:null}]).mode,"ordinal")
  assert.equal(timelineScale([{relativeDay:0,relativeDayOrigin:"first scan",timingSamePatient:false}]).mode,"ordinal")
  for (const value of [NaN,Infinity,"12",null,true]) assert.equal(normalizeRelativeDay(value),null)
})

test("same-day scans stay at the same coordinate, without a fabricated gap", () => {
  assert.deepEqual(timelineScale([{scanDate:"2024-01-01"},{scanDate:"2024-01-01"}]).positions,[0.5,0.5])
  assert.deepEqual(timelineTicks([{scanDate:"2024-01-01"},{scanDate:"2024-01-01"}]).map(t => [t.position, t.lane]), [[0.5, 0], [0.5, 1]])
  assert.deepEqual(timelineScale([]).positions,[])
})

test("axis labels are actual visits, never interpolated time values", () => {
  const days = [84, 126, 246, 316, 351, 442]
  const points = days.map(relativeDay => ({ relativeDay, relativeDayOrigin: "diagnosis" }))
  const ticks = timelineTicks(points)
  assert.deepEqual(ticks.map(t => t.label), days.map(day => `Day ${day}`))
  assert.deepEqual(ticks.map(t => t.position), days.map(day => (day - 84) / (442 - 84)))
  assert.deepEqual(timelineTicks([]), [])
})

test("close visits retain all labels in non-overlapping lanes at their true x positions", () => {
  const days = [91, 154, 158, 290, 366, 480]
  const ticks = timelineTicks(days.map(relativeDay => ({ relativeDay, relativeDayOrigin: "diagnosis" })))
  assert.equal(ticks.length, days.length)
  assert.notEqual(ticks[1].lane, ticks[2].lane)
  assert.ok(Math.abs(ticks[2].position - ticks[1].position - 4 / 389) < 1e-10)
  for (let i = 0; i < ticks.length; i++) {
    for (let j = i + 1; j < ticks.length; j++) {
      if (ticks[i].lane !== ticks[j].lane) continue
      const requiredGap = (ticks[i].label.length + ticks[j].label.length) * 12 * 0.32 + 12
      assert.ok((ticks[j].position - ticks[i].position) * 620 >= requiredGap)
    }
  }
})

test("visitDisplayLabel prefers dates, then numeric days, then a supplied non-generic label", () => {
  assert.equal(visitDisplayLabel({ scanDate: "2024-01-01", relativeDay: 12, dateLabel: "Day 5" }), "2024-01-01")
  assert.equal(visitDisplayLabel({ relativeDay: 56.40625, dateLabel: "Day 5" }), "Day 56.4")
  assert.equal(visitDisplayLabel({ dateLabel: "Day 102" }), "Day 102")
  assert.equal(visitDisplayLabel({ id: "patient-001-visit-01", dateLabel: "patient-001-visit-01" }), null)
  assert.equal(visitDisplayLabel({ label: "Patient A", dateLabel: "Patient A" }), null)
  for (const generic of ["Timepoint 1", "Time 2", "visit 3", "Scan 4", ""]) assert.equal(visitDisplayLabel({ dateLabel: generic }), null, generic)
})
