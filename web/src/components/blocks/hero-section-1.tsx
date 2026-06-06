'use client';
import React from 'react';
import Link from 'next/link';
import { ArrowRight, ChevronRight, Menu, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { AnimatedGroup } from '@/components/ui/animated-group';
import { cn } from '@/lib/utils';

const transitionVariants = {
  item: {
    hidden: { opacity: 0, filter: 'blur(12px)', y: 12 },
    visible: {
      opacity: 1,
      filter: 'blur(0px)',
      y: 0,
      transition: { type: 'spring', bounce: 0.3, duration: 1.5 },
    },
  },
};

export function HeroSection() {
  return (
    <>
      <HeroHeader />
      <main className="overflow-hidden">
        <div
          aria-hidden
          className="z-[2] absolute inset-0 pointer-events-none isolate opacity-50 contain-strict hidden lg:block">
          <div className="w-[35rem] h-[80rem] -translate-y-[350px] absolute left-0 top-0 -rotate-45 rounded-full bg-[radial-gradient(68.54%_68.72%_at_55.02%_31.46%,hsla(0,0%,85%,.08)_0,hsla(0,0%,55%,.02)_50%,hsla(0,0%,45%,0)_80%)]" />
          <div className="h-[80rem] absolute left-0 top-0 w-56 -rotate-45 rounded-full bg-[radial-gradient(50%_50%_at_50%_50%,hsla(0,0%,85%,.06)_0,hsla(0,0%,45%,.02)_80%,transparent_100%)] [translate:5%_-50%]" />
          <div className="h-[80rem] -translate-y-[350px] absolute left-0 top-0 w-56 -rotate-45 bg-[radial-gradient(50%_50%_at_50%_50%,hsla(0,0%,85%,.04)_0,hsla(0,0%,45%,.02)_80%,transparent_100%)]" />
        </div>
        <section>
          <div className="relative pt-24 md:pt-36">
            <AnimatedGroup
              variants={{
                container: { visible: { transition: { delayChildren: 1 } } },
                item: {
                  hidden: { opacity: 0, y: 20 },
                  visible: { opacity: 1, y: 0, transition: { type: 'spring', bounce: 0.3, duration: 2 } },
                },
              }}
              className="absolute inset-0 -z-20">
              <img
                src="https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=3276&q=80"
                alt="background"
                className="absolute inset-x-0 top-56 -z-20 hidden lg:top-32 dark:block w-full object-cover opacity-30"
                width="3276"
                height="4095"
              />
            </AnimatedGroup>
            <div
              aria-hidden
              className="absolute inset-0 -z-10 size-full [background:radial-gradient(125%_125%_at_50%_100%,transparent_0%,var(--background)_75%)]"
            />
            <div className="mx-auto max-w-7xl px-6">
              <div className="text-center sm:mx-auto lg:mr-auto lg:mt-0">
                <AnimatedGroup variants={transitionVariants}>
                  <Link
                    href="#link"
                    className="hover:bg-background dark:hover:border-t-border bg-muted group mx-auto flex w-fit items-center gap-4 rounded-full border p-1 pl-4 shadow-md shadow-black/5 transition-all duration-300 dark:border-t-white/5 dark:shadow-zinc-950">
                    <span className="text-foreground text-sm">Introducing Support for AI Models</span>
                    <span className="dark:border-background block h-4 w-0.5 border-l bg-white dark:bg-zinc-700"></span>
                    <div className="bg-background group-hover:bg-muted size-6 overflow-hidden rounded-full duration-500">
                      <div className="flex w-12 -translate-x-1/2 duration-500 ease-in-out group-hover:translate-x-0">
                        <span className="flex size-6"><ArrowRight className="m-auto size-3" /></span>
                        <span className="flex size-6"><ArrowRight className="m-auto size-3" /></span>
                      </div>
                    </div>
                  </Link>

                  <h1 className="mt-8 max-w-4xl mx-auto text-balance text-6xl md:text-7xl lg:mt-16 xl:text-[5.25rem]">
                    Modern Solutions for Customer Engagement
                  </h1>
                  <p className="mx-auto mt-8 max-w-2xl text-balance text-lg">
                    Highly customizable components for building modern websites and applications that look and feel the way you mean it.
                  </p>
                </AnimatedGroup>

                <AnimatedGroup
                  variants={{
                    container: { visible: { transition: { staggerChildren: 0.05, delayChildren: 0.75 } } },
                    ...transitionVariants,
                  }}
                  className="mt-12 flex flex-col items-center justify-center gap-2 md:flex-row">
                  <div className="bg-foreground/10 rounded-[14px] border p-0.5">
                    <Button asChild size="lg" className="rounded-xl px-5 text-base">
                      <Link href="#link"><span className="text-nowrap">Start Building</span></Link>
                    </Button>
                  </div>
                  <Button asChild size="lg" variant="ghost" className="rounded-xl px-5">
                    <Link href="#link"><span className="text-nowrap">Request a demo</span></Link>
                  </Button>
                </AnimatedGroup>
              </div>
            </div>

            <AnimatedGroup
              variants={{
                container: { visible: { transition: { staggerChildren: 0.05, delayChildren: 0.75 } } },
                ...transitionVariants,
              }}>
              <div className="relative -mr-56 mt-8 overflow-hidden px-2 sm:mr-0 sm:mt-12 md:mt-20">
                <div
                  aria-hidden
                  className="bg-gradient-to-b to-background absolute inset-0 z-10 from-transparent from-35%"
                />
                <div className="inset-shadow-2xs ring-background dark:inset-shadow-white/20 bg-background relative mx-auto max-w-6xl overflow-hidden rounded-2xl border p-4 shadow-lg shadow-zinc-950/15 ring-1">
                  <img
                    className="bg-background aspect-[15/8] relative hidden rounded-2xl dark:block w-full object-cover"
                    src="https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=2700&q=80"
                    alt="app screen"
                    width="2700"
                    height="1440"
                  />
                  <img
                    className="border-border/25 aspect-[15/8] relative rounded-2xl border dark:hidden w-full object-cover"
                    src="https://images.unsplash.com/photo-1460925895917-afdab827c52f?w=2700&q=80"
                    alt="app screen"
                    width="2700"
                    height="1440"
                  />
                </div>
              </div>
            </AnimatedGroup>
          </div>
        </section>

        <section className="bg-background pb-16 pt-16 md:pb-32">
          <div className="group relative m-auto max-w-5xl px-6">
            <div className="absolute inset-0 z-10 flex scale-95 items-center justify-center opacity-0 duration-500 group-hover:scale-100 group-hover:opacity-100">
              <Link href="/" className="block text-sm duration-150 hover:opacity-75">
                <span>Meet Our Customers</span>
                <ChevronRight className="ml-1 inline-block size-3" />
              </Link>
            </div>
            <div className="group-hover:blur-sm mx-auto mt-12 grid max-w-2xl grid-cols-4 gap-x-12 gap-y-8 transition-all duration-500 group-hover:opacity-50 sm:gap-x-16 sm:gap-y-14">
              {[
                { src: 'https://html.tailus.io/blocks/customers/nvidia.svg', alt: 'Nvidia', h: 'h-5' },
                { src: 'https://html.tailus.io/blocks/customers/column.svg', alt: 'Column', h: 'h-4' },
                { src: 'https://html.tailus.io/blocks/customers/github.svg', alt: 'GitHub', h: 'h-4' },
                { src: 'https://html.tailus.io/blocks/customers/nike.svg', alt: 'Nike', h: 'h-5' },
                { src: 'https://html.tailus.io/blocks/customers/lemonsqueezy.svg', alt: 'Lemon Squeezy', h: 'h-5' },
                { src: 'https://html.tailus.io/blocks/customers/laravel.svg', alt: 'Laravel', h: 'h-4' },
                { src: 'https://html.tailus.io/blocks/customers/lilly.svg', alt: 'Lilly', h: 'h-7' },
                { src: 'https://html.tailus.io/blocks/customers/openai.svg', alt: 'OpenAI', h: 'h-6' },
              ].map((logo) => (
                <div key={logo.alt} className="flex">
                  <img className={cn('mx-auto w-fit dark:invert', logo.h)} src={logo.src} alt={`${logo.alt} Logo`} width="auto" />
                </div>
              ))}
            </div>
          </div>
        </section>
      </main>
    </>
  );
}

const menuItems = [
  { name: 'Features', href: '#link' },
  { name: 'Solution', href: '#link' },
  { name: 'Pricing', href: '#link' },
  { name: 'About', href: '#link' },
];

const HeroHeader = () => {
  const [menuState, setMenuState] = React.useState(false);
  const [isScrolled, setIsScrolled] = React.useState(false);

  React.useEffect(() => {
    const handleScroll = () => setIsScrolled(window.scrollY > 50);
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  return (
    <header>
      <nav data-state={menuState ? 'active' : undefined} className="fixed z-20 w-full px-2 group">
        <div className={cn('mx-auto mt-2 max-w-6xl px-6 transition-all duration-300 lg:px-12', isScrolled && 'bg-background/50 max-w-4xl rounded-2xl border backdrop-blur-lg lg:px-5')}>
          <div className="relative flex flex-wrap items-center justify-between gap-6 py-3 lg:gap-0 lg:py-4">
            <div className="flex w-full justify-between lg:w-auto">
              <Link href="/" aria-label="home" className="flex items-center space-x-2">
                <Logo />
              </Link>
              <button
                onClick={() => setMenuState(!menuState)}
                aria-label={menuState ? 'Close Menu' : 'Open Menu'}
                className="relative z-20 -m-2.5 -mr-4 block cursor-pointer p-2.5 lg:hidden">
                <Menu className="group-data-[state=active]:scale-0 group-data-[state=active]:opacity-0 m-auto size-6 duration-200" />
                <X className="group-data-[state=active]:rotate-0 group-data-[state=active]:scale-100 group-data-[state=active]:opacity-100 absolute inset-0 m-auto size-6 -rotate-180 scale-0 opacity-0 duration-200" />
              </button>
            </div>

            <div className="absolute inset-0 m-auto hidden size-fit lg:block">
              <ul className="flex gap-8 text-sm">
                {menuItems.map((item, index) => (
                  <li key={index}>
                    <Link href={item.href} className="text-muted-foreground hover:text-accent-foreground block duration-150">
                      <span>{item.name}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>

            <div className="bg-background group-data-[state=active]:block lg:group-data-[state=active]:flex mb-6 hidden w-full flex-wrap items-center justify-end space-y-8 rounded-3xl border p-6 shadow-2xl shadow-zinc-300/20 md:flex-nowrap lg:m-0 lg:flex lg:w-fit lg:gap-6 lg:space-y-0 lg:border-transparent lg:bg-transparent lg:p-0 lg:shadow-none dark:shadow-none dark:lg:bg-transparent">
              <div className="lg:hidden">
                <ul className="space-y-6 text-base">
                  {menuItems.map((item, index) => (
                    <li key={index}>
                      <Link href={item.href} className="text-muted-foreground hover:text-accent-foreground block duration-150">
                        <span>{item.name}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="flex w-full flex-col space-y-3 sm:flex-row sm:gap-3 sm:space-y-0 md:w-fit">
                <Button asChild variant="outline" size="sm" className={cn(isScrolled && 'lg:hidden')}>
                  <Link href="#"><span>Login</span></Link>
                </Button>
                <Button asChild size="sm" className={cn(isScrolled && 'lg:hidden')}>
                  <Link href="#"><span>Sign Up</span></Link>
                </Button>
                <Button asChild size="sm" className={cn(isScrolled ? 'lg:inline-flex' : 'hidden')}>
                  <Link href="#"><span>Get Started</span></Link>
                </Button>
              </div>
            </div>
          </div>
        </div>
      </nav>
    </header>
  );
};

const Logo = ({ className }: { className?: string }) => (
  <svg viewBox="0 0 78 18" fill="none" xmlns="http://www.w3.org/2000/svg" className={cn('h-5 w-auto', className)}>
    <path d="M3 0H5V18H3V0ZM13 0H15V18H13V0ZM18 3V5H0V3H18ZM0 15V13H18V15H0Z" fill="url(#logo-gradient)" />
    <path d="M27.06 7.054V12.239C27.06 12.5903 27.1393 12.8453 27.298 13.004C27.468 13.1513 27.7513 13.225 28.148 13.225H29.338V14.84H27.808C26.9353 14.84 26.2667 14.636 25.802 14.228C25.3373 13.82 25.105 13.157 25.105 12.239V7.054H24V5.473H25.105V3.144H27.06V5.473H29.338V7.054H27.06Z" fill="currentColor" />
    <defs>
      <linearGradient id="logo-gradient" x1="10" y1="0" x2="10" y2="20" gradientUnits="userSpaceOnUse">
        <stop stopColor="#9B99FE" />
        <stop offset="1" stopColor="#2BC8B7" />
      </linearGradient>
    </defs>
  </svg>
);
