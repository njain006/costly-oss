// Empty-table message for Snowflake pages that read QUERY_HISTORY.
// `denied` comes from the API: true only when the role could not read the
// view. `timedOut` means Snowflake was too slow for this range, which is
// not a permissions problem. Otherwise the range is simply empty.
export default function AccessHint({
  what = "query history",
  denied,
  timedOut,
}: {
  what?: string;
  denied?: boolean;
  timedOut?: boolean;
}) {
  if (timedOut && !denied) {
    return (
      <div className="py-10 text-center text-sm text-muted-foreground">
        <p className="font-medium text-slate-600">Snowflake took too long to return {what} for this range.</p>
        <p className="mt-1">Pick a shorter range, or press Refresh to try again.</p>
      </div>
    );
  }
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
