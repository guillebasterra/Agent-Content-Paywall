import { BLURRED_FILLER } from "@/lib/api";

export default function Tile({ title, clear, children }: { title: string; clear: string; children: React.ReactNode }) {
  return (
    <>
      <span className="tile-title">{title}</span>
      {clear && <span className="tile-clear">{clear}</span>}
      <span className="tile-blurred" aria-hidden="true">{`${BLURRED_FILLER} ${BLURRED_FILLER}`}</span>
      <span className="tile-footer">{children}</span>
    </>
  );
}
