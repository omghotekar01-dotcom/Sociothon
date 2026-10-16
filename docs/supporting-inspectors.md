# Supporting inspector assignments

An open case keeps one lead inspector and can have up to ten supporting inspectors. Operators and administrators manage the team in Evidence Passport → Take action. Each change requires a reason and the current case version. The decision history retains previous and new supporting IDs, actor, timestamp and reason.

Supporting inspectors must be active inspectors authorized for the case's domain and zone. They see assigned cases in Assigned work and receive case notifications. They can record inspection, intervention and follow-up evidence and use the existing monitoring transition. They cannot assign colleagues or close cases. Removing an assignment removes case access and hides its notifications; earlier evidence and decisions remain intact. Revoked domain/zone permission also removes access even if the assignment remains recorded.

The lead cannot also be listed as supporting. Promoting a supporting inspector to lead removes their supporting entry in the same transaction; the former lead is not automatically retained. Supporting-team changes do not change case status. A stale version rejects and rolls back the entire replacement.

Migration `0003_supporting_inspectors` adds the `case_inspectors` join table without rewriting existing cases. An upgrade test starts at revision 0002, preserves an existing case and its evidence/version, and runs the migration twice. PostgreSQL execution remains unverified.

Local demo account: `support@civicsignal.local`, password `CivicDemo!2026`. Kiran is a second inspector, available through the regular email/password form. Demo seeding adds this account to existing demo databases without resetting existing users. It does not create it in production mode.

API and browser verification cover team replacement, field findings, removal, and retained evidence. API tests also cover unauthorized roles, invalid or duplicate inspectors, lead exclusion, scope revocation, lead promotion and stale-version rollback. Specialized domain inspection forms remain separate acceptance work.
