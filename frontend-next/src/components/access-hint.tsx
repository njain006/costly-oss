// Empty-table message for Snowflake pages that read QUERY_HISTORY.
// `denied` comes from the API: true only when the role could not read the
// view. Otherwise the range is simply empty and we say so.
export default function AccessHint({ what = "query history", denied }: { what?: string; denied?: boolean }) {
  if (!denied) {
    return (
      <div className="py-10 text-center text-sm text-muted-foreground">
        No {what} in this date range.
      </div>
    );
  }
  return (
    <div className="py-10 text-center text-sm text-muted-foreground">
      <p className="font-medium text-slate-600">No {what} to show: the connected role cannot read query history.</p>
      <p className="mt-1 max-w-xl mx-auto">
        This page reads <code className="text-xs">SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY</code>, which needs the
        <code className="text-xs"> SNOWFLAKE.GOVERNANCE_VIEWER</code> database role. That role also exposes query
        text, so get a security sign-off before granting it. Cost per user and per warehouse still work without it.
      </p>
    </div>
  );
}
