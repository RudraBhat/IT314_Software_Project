import { redirect } from "next/navigation";
import { currentUser } from "@/lib/session";
import { CitizenDashboardClient } from "./client-view";

export default async function CitizenDashboardPage() {
  const user = await currentUser();
  if (!user) {
    redirect("/login?next=/citizen/dashboard");
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
  if (user.role !== "NORMAL_USER") {
    redirect("/");
  }

  return (
    <CitizenDashboardClient
      user={{
        id: user.user_id,
        name: user.full_name || "Citizen",
        phone: "",
        email: user.email || "",
      }}
    />
  );
}
