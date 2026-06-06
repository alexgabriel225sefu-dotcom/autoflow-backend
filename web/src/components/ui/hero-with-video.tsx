"use client";

import React, { useState, useRef } from 'react';
import { Play, Pause, Menu, X } from 'lucide-react';

interface NavbarHeroProps {
  onGetAccess?: () => void;
}

export const NavbarHero: React.FC<NavbarHeroProps> = ({ onGetAccess }) => {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isVideoPlaying, setIsVideoPlaying] = useState(false);
  const [isVideoPaused, setIsVideoPaused] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  const handlePlayVideo = () => {
    if (videoRef.current) {
      videoRef.current.play();
      setIsVideoPlaying(true);
      setIsVideoPaused(false);
    }
  };

  const handlePauseVideo = () => {
    if (videoRef.current) {
      videoRef.current.pause();
      setIsVideoPaused(true);
    }
  };

  const handleResumeVideo = () => {
    if (videoRef.current) {
      videoRef.current.play();
      setIsVideoPaused(false);
    }
  };

  const handleVideoEnded = () => {
    setIsVideoPlaying(false);
    setIsVideoPaused(false);
  };

  return (
    <>
      {/* Fixed Navbar */}
      <nav
        className="fixed top-0 left-0 right-0 z-[200] h-[58px] flex items-center justify-between px-6"
        style={{ borderBottom: "1px solid transparent" }}
      >
        <a href="#" className="flex items-center gap-2 text-[13px] font-bold text-white no-underline">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="22 7 13.5 15.5 8.5 10.5 2 17" />
            <polyline points="16 7 22 7 22 13" />
          </svg>
          Apex Trade Bot
        </a>

        <div className="hidden md:flex gap-6">
          {([["How It Works", "#how"], ["Features", "#features"], ["Pricing", "#pricing"]] as [string, string][]).map(([label, href]) => (
            <a
              key={label}
              href={href}
              className="text-[12px] no-underline transition-colors"
              style={{ color: "rgba(255,255,255,.4)" }}
            >
              {label}
            </a>
          ))}
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={onGetAccess}
            className="hidden md:block px-4 py-2 text-black text-[12px] font-bold rounded-[8px] transition-opacity hover:opacity-90 cursor-pointer"
            style={{ background: "#f59e0b" }}
          >
            Get Access →
          </button>
          <button
            onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
            className="md:hidden p-2 cursor-pointer"
            style={{ color: "rgba(255,255,255,.5)" }}
            aria-label="Toggle menu"
          >
            {isMobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>
      </nav>

      {/* Mobile Menu */}
      {isMobileMenuOpen && (
        <div
          className="fixed top-[58px] left-0 right-0 z-[199] py-3 px-4"
          style={{ background: "rgba(3,5,8,.97)", borderBottom: "1px solid rgba(255,255,255,.06)" }}
        >
          {([["How It Works", "#how"], ["Features", "#features"], ["Pricing", "#pricing"]] as [string, string][]).map(([label, href]) => (
            <a
              key={label}
              href={href}
              onClick={() => setIsMobileMenuOpen(false)}
              className="block py-2 text-[13px] no-underline"
              style={{ color: "rgba(255,255,255,.5)" }}
            >
              {label}
            </a>
          ))}
          <button
            onClick={() => { onGetAccess?.(); setIsMobileMenuOpen(false); }}
            className="w-full mt-2 py-2.5 text-black text-[13px] font-bold rounded-[8px] cursor-pointer"
            style={{ background: "#f59e0b" }}
          >
            Get Access →
          </button>
        </div>
      )}

      {/* Hero Section */}
      <section className="flex flex-col items-center justify-center text-center px-6 pt-28 pb-10">
        <div className="w-full max-w-6xl mx-auto">
          {/* Badge */}
          <div
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-[11px] font-medium mb-8"
            style={{ border: "1px solid rgba(255,255,255,.1)", background: "rgba(255,255,255,.04)", color: "rgba(255,255,255,.4)" }}
          >
            500+ bots deployed
            <span className="w-px h-2.5" style={{ background: "rgba(255,255,255,.12)" }} />
            Full source code · No subscriptions
          </div>

          {/* Headline */}
          <h1
            className="font-black leading-[.96] mb-6 max-w-[820px] mx-auto"
            style={{ fontSize: "clamp(42px,6vw,82px)", letterSpacing: "-3px" }}
          >
            The trading bot<br />
            you{" "}
            <span style={{ color: "#f59e0b" }}>actually own.</span>
          </h1>

          {/* Subhead */}
          <p
            className="leading-[1.8] max-w-[520px] mx-auto mb-10 font-light"
            style={{ fontSize: "clamp(14px,1.4vw,17px)", color: "rgba(255,255,255,.45)" }}
          >
            Others charge $99/month for a bot you don't control. Buy once, get every line of code, deploy it yourself. No fees. No lock-in. No black box.
          </p>

          {/* CTAs */}
          <div className="flex gap-3 flex-wrap justify-center mb-10">
            <button
              onClick={onGetAccess}
              className="inline-flex items-center gap-2 px-7 py-3.5 text-black text-[13px] font-extrabold rounded-[10px] transition-opacity hover:opacity-90 cursor-pointer"
              style={{ background: "#f59e0b", boxShadow: "0 0 40px rgba(245,158,11,.2)" }}
            >
              Get the Bot — $297
            </button>
            <a
              href="#how"
              className="inline-flex items-center gap-2 px-6 py-3.5 text-[13px] rounded-[10px] no-underline transition-colors"
              style={{ border: "1px solid rgba(255,255,255,.1)", color: "rgba(255,255,255,.55)" }}
            >
              See How It Works
            </a>
          </div>

          {/* Trust badges */}
          <div className="flex items-center gap-6 flex-wrap justify-center mb-12">
            {["Stripe Encrypted", "Instant Delivery", "No Monthly Fees"].map(t => (
              <span key={t} className="flex items-center gap-1.5 text-[11px]" style={{ color: "rgba(255,255,255,.25)" }}>
                <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                {t}
              </span>
            ))}
          </div>

          {/* Video / Image showcase */}
          <div
            className="relative w-full aspect-video rounded-[18px] overflow-hidden"
            style={{ border: "1px solid rgba(255,255,255,.08)", boxShadow: "0 40px 80px rgba(0,0,0,.6)" }}
          >
            <img
              src="https://images.unsplash.com/photo-1446776811953-b23d57bd21aa?ixlib=rb-4.0.3&auto=format&fit=crop&w=2072&q=80"
              alt="Trading platform overview"
              className={`w-full h-full absolute inset-0 object-cover transition-opacity duration-500 ${isVideoPlaying ? 'opacity-0' : 'opacity-100'}`}
            />
            <video
              ref={videoRef}
              src="https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4"
              className={`w-full h-full absolute inset-0 object-cover transition-opacity duration-500 ${isVideoPlaying ? 'opacity-100' : 'opacity-0'}`}
              onEnded={handleVideoEnded}
              playsInline
              muted
            />
            <div className="absolute bottom-5 right-5 z-10">
              {!isVideoPlaying ? (
                <button
                  onClick={handlePlayVideo}
                  className="w-14 h-14 rounded-full flex items-center justify-center transition-all duration-200 hover:scale-105 cursor-pointer"
                  style={{ background: "rgba(255,255,255,.15)", backdropFilter: "blur(12px)", border: "1px solid rgba(255,255,255,.25)" }}
                  aria-label="Play video"
                >
                  <Play className="w-7 h-7 text-white fill-white ml-1" />
                </button>
              ) : (
                <button
                  onClick={isVideoPaused ? handleResumeVideo : handlePauseVideo}
                  className="w-14 h-14 rounded-full flex items-center justify-center transition-all duration-200 hover:scale-105 cursor-pointer"
                  style={{ background: "rgba(255,255,255,.15)", backdropFilter: "blur(12px)", border: "1px solid rgba(255,255,255,.25)" }}
                  aria-label={isVideoPaused ? "Resume video" : "Pause video"}
                >
                  {isVideoPaused
                    ? <Play className="w-7 h-7 text-white fill-white ml-1" />
                    : <Pause className="w-7 h-7 text-white fill-white" />
                  }
                </button>
              )}
            </div>
          </div>
        </div>
      </section>
    </>
  );
};
