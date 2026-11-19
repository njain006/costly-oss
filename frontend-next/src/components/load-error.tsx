import { AlertTriangle } from "lucide-react";

// Banner for a page whose data could not be loaded (e.g. the Snowflake
// warehouse hit its resource monitor quota). Shows the backend's message.
export default function LoadError({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div role="alert" className="mb-6 flex gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
      <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
      <div>
        <p className="font-medium">This page could not be refreshed.</p>
        <p className="mt-0.5">{error}</p>
      </div>
    </div>
  );
}
