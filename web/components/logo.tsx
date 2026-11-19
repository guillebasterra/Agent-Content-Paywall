import Image from "next/image";

export default function Logo() {
  return (
    <span className="logo">
      <Image src="/aitollgate-logo.png" width={48} height={48} alt="" priority />
      <span>Toll Gate</span>
    </span>
  );
}
