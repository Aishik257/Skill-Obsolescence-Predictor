import { Link } from "react-router-dom";
import { EmptyState } from "@/components/States";

export default function NotFound() {
  return <EmptyState title="Page not found" hint="That address does not exist." action={<Link className="btn-primary" to="/">Back to the dashboard</Link>} />;
}
