import { PublicShell } from "@/components/public-shell";
import { ButtonLink, PageTitle } from "@/components/ui";

export default function NotFound() {
  return (
    <PublicShell>
      <PageTitle title="Page not found" subtitle="That page doesn't exist in this wallet." />
      <ButtonLink href="/">Go to X Money</ButtonLink>
    </PublicShell>
  );
}
