import { redirect } from "next/navigation";
import { currentUser } from "@/lib/session";
import { CitizenDashboardClient } from "./client-view";

export default async function CitizenDashboardPage() {
  const user = await currentUser();
  if (!user || user.role !== "NORMAL_USER") {
    redirect("/login");
  }

  return (
    <CitizenDashboardClient
      user={{
        id: user.user_id,
        name: user.full_name || "Citizen",
        phone: "",
      }}
    />
  );
}
