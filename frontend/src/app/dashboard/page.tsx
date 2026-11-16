import { redirect } from "next/navigation";
import { currentUser } from "@/lib/session";

export default async function DashboardPage() {
  const user = await currentUser();
  if (!user) {
    redirect("/login?next=/dashboard");
  }

  if (user.role === "DISASTER_MGMT") {
    redirect("/dm");
  }
  if (user.role === "FIELD_TEAM") {
    redirect("/field");
  }
  if (user.role === "APP_MGMT") {
    redirect("/admin");
  }

  redirect("/citizen/dashboard");
}
