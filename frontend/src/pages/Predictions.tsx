import { api } from "@/api/endpoints";
import SkillListPage from "@/components/SkillListPage";

export default function Predictions() {
  return (
    <SkillListPage title="Predictions" showLimitations defaultSort={{ key: "obsolescence_score", order: "desc" }} loader={api.predictions}
      subtitle="Obsolescence scores range from 0 (safe) to 100 (high risk of losing market demand). They describe job-posting demand, not technical quality." />
  );
}
