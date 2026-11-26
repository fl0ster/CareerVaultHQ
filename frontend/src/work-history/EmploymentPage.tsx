import { useEffect, useState } from "react";
import "../interviews/interviews.css";
import "../companies/tags.css";
import CompanyDialog from "../companies/CompanyDialog.tsx";
import { CompanyTagBadge } from "../companies/CompanyTag.tsx";
import "./work-history.css";
import {
  WORK_HISTORY_CHANGED,
  type WorkHistoryEntry,
  workHistoryApi,
} from "./api.ts";

/** A position held now: started, with no end date. */
const isCurrentPosition = (e: WorkHistoryEntry) =>
  e.kind === "job" && e.date_end === null && !e.pending;

const since = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    year: "numeric",
  });

/** The positions currently held, one card each (styled like the interview cards). */
export default function EmploymentPage() {
  const [entries, setEntries] = useState<WorkHistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Company popup: its tag and application stats.
  const [companyId, setCompanyId] = useState<number | null>(null);

  useEffect(() => {
    const load = () =>
      workHistoryApi
        .list()
        .then((all) => setEntries(all.filter(isCurrentPosition)))
        .catch((e: Error) => setError(e.message));
    load();
    window.addEventListener(WORK_HISTORY_CHANGED, load);
    return () => window.removeEventListener(WORK_HISTORY_CHANGED, load);
  }, []);

  if (error)
    return <p className="muted">Could not load your employment: {error}</p>;
  if (!entries) return <p className="muted">Loading…</p>;
  if (entries.length === 0)
    return <p className="muted">No current positions.</p>;

  return (
    <>
      <ul className="iv-grid">
        {entries.map((e) => (
          <li key={e.id}>
            <article className="iv-card">
              <header className="iv-card-head">
                <div className="iv-card-title">
                  <h3 className="employment-role">{e.role}</h3>
                  <div className="iv-card-meta">
                    {e.company_id != null ? (
                      <CompanyTagBadge
                        companyId={e.company_id}
                        tag={e.company_tag}
                        name={e.employer}
                        onOpenCompany={setCompanyId}
                      />
                    ) : (
                      <span>{e.employer}</span>
                    )}
                    {e.location && <span className="muted">{e.location}</span>}
                  </div>
                </div>
              </header>
              <p className="muted employment-since">
                Since {since(e.date_start)}
              </p>
            </article>
          </li>
        ))}
      </ul>
      {companyId != null && (
        <CompanyDialog
          key={companyId}
          companyId={companyId}
          onClose={() => setCompanyId(null)}
        />
      )}
    </>
  );
}
