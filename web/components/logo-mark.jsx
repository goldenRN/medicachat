export default function LogoMark({ className = "logo-badge" }) {
  return (
    <div className={className} aria-hidden="true">
      <img src="/profile.jpg" alt="" />
    </div>
  );
}
