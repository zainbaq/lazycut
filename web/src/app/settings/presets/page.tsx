import { redirect } from "next/navigation";

/** `/settings/presets` opens the General preset; the list is beside it. */
export default function PresetsIndex() {
  redirect("/settings/presets/general");
}
