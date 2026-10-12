import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/endpoints";
import { RiskBadge, StatusBadge } from "@/components/Badges";
import { Async, EmptyState, ErrorState, Loading } from "@/components/States";
import { Card, PageHeader } from "@/components/Ui";
import { useApi } from "@/hooks/useApi";
import type { LearningPath, RecommendationItem, SkillGap, SkillSummary } from "@/types/api";
import { num, pct, signedPct } from "@/utils/format";

function parseSkills(text: string) {
  return [...new Set(text.split(/[,\n;]/).map((skill) => skill.trim()).filter(Boolean))];
}

function SkillLinks({ skills }: { skills: SkillSummary[] }) {
  if (!skills.length) return <p className="text-sm text-slate-500">No skills in this group for your inputs.</p>;
  return (
    <ul className="divide-y divide-slate-100">
      {skills.map((skill) => (
        <li key={skill.skill_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
          <div><Link to={`/skills/${skill.skill_id}`} className="text-sm font-medium text-brand-700 hover:underline">{skill.name}</Link>
            <p className="text-xs text-slate-500">{skill.category} · demand {pct(skill.current_demand)}</p></div>
          <div className="flex items-center gap-2"><StatusBadge status={skill.trend_status} /><RiskBadge level={skill.risk_level} /></div>
        </li>
      ))}
    </ul>
  );
}

function RecommendationList({ items }: { items: RecommendationItem[] }) {
  if (!items.length) return <p className="text-sm text-slate-500">No recommendations for this section.</p>;
  return (
    <ol className="divide-y divide-slate-100">
      {items.map((item, index) => (
        <li key={item.skill_id} className="flex gap-3 py-3">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-50 text-xs font-semibold text-brand-700">{index + 1}</span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Link to={`/skills/${item.skill_id}`} className="text-sm font-medium text-brand-700 hover:underline">{item.name}</Link>
              <span className="text-xs text-slate-500">Priority {num(item.priority_score, 0)} · {item.priority}</span>
            </div>
            <p className="mt-0.5 text-xs text-slate-500">{item.category} · role demand {pct(item.role_demand)} · growth {signedPct(item.role_growth)}</p>
            {!!item.reasons.length && <ul className="mt-1 list-disc pl-4 text-xs text-slate-600">{item.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
          </div>
        </li>
      ))}
    </ol>
  );
}

export default function MySkills() {
  const roles = useApi(() => api.filterOptions(), []);
  const [role, setRole] = useState("");
  const [skillsText, setSkillsText] = useState("");
  const [gap, setGap] = useState<SkillGap | null>(null);
  const [path, setPath] = useState<LearningPath | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const currentSkills = parseSkills(skillsText);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    setGap(null);
    setPath(null);
    try {
      const [gapResult, pathResult] = await Promise.all([
        api.skillGap(role || null, currentSkills),
        api.learningPath(role || null, currentSkills),
      ]);
      setGap(gapResult);
      setPath(pathResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load skill recommendations.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <PageHeader title="My skills" subtitle="Compare your current skills with market demand for a role and get a ranked learning path." />
      <div className="space-y-5">
        <Card title="Build your profile" subtitle="Your profile is only used to request these recommendations; it is not saved.">
          <form onSubmit={submit} className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label htmlFor="skills-role" className="mb-1 block text-sm font-medium text-slate-700">Target role</label>
                <Async state={roles}>
                  {(data) => (
                    <select id="skills-role" className="input" value={role} onChange={(event) => setRole(event.target.value)}>
                      <option value="">Any role</option>
                      {data.roles.map((item) => <option key={item.value} value={item.value}>{item.value} ({num(item.postings)} postings)</option>)}
                    </select>
                  )}
                </Async>
              </div>
              <div>
                <label htmlFor="skills-current" className="mb-1 block text-sm font-medium text-slate-700">Skills you already have</label>
                <textarea id="skills-current" className="input min-h-24" placeholder="For example: Python, SQL, Docker" value={skillsText} onChange={(event) => setSkillsText(event.target.value)} />
                <p className="mt-1 text-xs text-slate-500">{currentSkills.length} skill{currentSkills.length === 1 ? "" : "s"} entered. Separate with commas or new lines.</p>
              </div>
            </div>
            {error && <ErrorState message={error} />}
            <button type="submit" className="btn-primary" disabled={loading || roles.loading || Boolean(roles.error)}>
              {loading ? "Finding recommendations..." : "Show my skill gap"}
            </button>
          </form>
        </Card>

        {loading && !gap && <Loading label="Comparing your skills with the market..." />}
        {gap && path && (
          <>
            <div className="grid gap-5 lg:grid-cols-2">
              <Card title="Skills to strengthen" subtitle="Existing skills where the market signal suggests further investment.">
                <RecommendationList items={gap.skills_to_strengthen} />
              </Card>
              <Card title="Emerging skills to consider" subtitle="Skills with a growing or emerging signal for your target role.">
                <RecommendationList items={gap.emerging_to_consider} />
              </Card>
              <Card title="Your recognized strengths" subtitle="Skills from your profile found in the skill taxonomy.">
                <SkillLinks skills={gap.strong_skills} />
              </Card>
              <Card title="At-risk skills in your profile" subtitle="These can still be valuable; the label reflects posting demand, not technical quality.">
                <SkillLinks skills={gap.at_risk_skills} />
              </Card>
            </div>

            <Card title="Suggested learning path" subtitle={`${num(path.role_postings)} postings considered · ${path.method}`}>
              <RecommendationList items={path.recommendations} />
            </Card>

            {(gap.unrecognized.length > 0 || path.unrecognized.length > 0) && (
              <Card title="Could not match these skills">
                <p className="text-sm text-slate-600">{[...new Set([...gap.unrecognized, ...path.unrecognized])].join(", ")}</p>
                <p className="mt-1 text-xs text-slate-500">Try a common skill name or spelling from the project taxonomy.</p>
              </Card>
            )}
            {!gap.skills_to_strengthen.length && !gap.emerging_to_consider.length && !path.recommendations.length &&
              <EmptyState title="No learning recommendations yet" hint="Try adding current skills or choosing a more specific target role." />}
          </>
        )}
      </div>
    </>
  );
}
