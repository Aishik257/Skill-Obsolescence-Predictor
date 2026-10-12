import { api } from "@/api/endpoints";
import SkillListPage from "@/components/SkillListPage";

export default function Skills() {
  return (
    <SkillListPage title="Skills" defaultSort={{ key: "current_demand", order: "desc" }} loader={api.skills}
      subtitle="Every skill extracted from job postings, with demand (share of postings), trend, obsolescence score and confidence. Click a column to sort, a skill for details." />
  );
}
