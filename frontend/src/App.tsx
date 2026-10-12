import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { FilterProvider } from "./hooks/useFilters";
import About from "./pages/About";
import Analytics from "./pages/Analytics";
import Dashboard from "./pages/Dashboard";
import Forecasts from "./pages/Forecasts";
import JobData from "./pages/JobData";
import MySkills from "./pages/MySkills";
import NotFound from "./pages/NotFound";
import Predictions from "./pages/Predictions";
import SkillDetailPage from "./pages/SkillDetail";
import Skills from "./pages/Skills";
import Trends from "./pages/Trends";

export default function App() {
  return (
    <FilterProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="skills" element={<Skills />} />
          <Route path="skills/:id" element={<SkillDetailPage />} />
          <Route path="trends" element={<Trends />} />
          <Route path="predictions" element={<Predictions />} />
          <Route path="forecasts" element={<Forecasts />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="my-skills" element={<MySkills />} />
          <Route path="data" element={<JobData />} />
          <Route path="about" element={<About />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </FilterProvider>
  );
}
