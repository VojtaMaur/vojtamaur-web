export type Lang = "cs" | "en";
export type SectionId = "volna-tvorba" | "vystavy" | "cestovani";

export const defaultLang: Lang = "cs";
export const supportedLangs: Lang[] = ["cs", "en"];

export const ui = {
  cs: {
    siteTitle: "Vojta Maur",
    motto: "Tvořit je můj základní instinkt",
    showAll: "Zobrazit vše",
    sections: {
      "volna-tvorba": "Volná tvorba",
      vystavy: "Výstavy",
      cestovani: "Cestování",
      videos: "Propagační videa"
    },
    home: {
      metaTitle: "Vojta Maur",
      metaDescription: "Osobní web Vojty Maura",
      sections: {
        "volna-tvorba": {
          title: "Volná tvorba",
          description: "Umění je nejvyšší formou naděje (Documenta 7)"
        },
        vystavy: {
          title: "Výstavy",
          description: "Když mě někdo omylem vypustí z ohrádky, vznikne tohle"
        },
        cestovani: {
          title: "Cestování",
          description: "Respektuji místní zvyky a tradice"
        },
        videos: {
          title: "Propagační videa",
          description: "Galerie jsou výstavní skříní mé tvorby... i když vystavuje někdo jiný..."
        }
      },
      about: {
        title: "O mně",
        description: "Hraju si se systémy a strukturami, kde člověk není ani středem, ani cílem",
        embedTitle: "3D sken hlavy",
        paragraphs: [
          "Již v raném věku jsem se zajímal o umění. Tři roky jsem navštěvoval základní uměleckou školu, kde jsem se seznámil s různými tradičními výtvarnými technikami. Vždy mě fascinovaly počítače, pročež jsem se sám začal učit pracovat ve 2D i 3D softwarech. Ještě před dokončením základní školy jsem také začal natáčet dokumentární videa z každé vernisáže v Galerii města Plzně. Spolupráci s touto galerií jsem ukončil až po třech letech, a to v momentě, kdy jsem dostal za úkol dát ve videu slovo Martinu Baxovi, který se vernisáže zúčastnil. Situaci jsem komentoval větou: „Dokumentuju umění a ne politiky!“.",
          "Vystudoval jsem obor Multimediální tvorba na Střední odborné škole obchodu, užitého umění a designu v Plzni. Tato nepříliš náročná škola mi poskytla dost času a prostoru pro studium zdánlivě nesouvisejících disciplín, zejména programování, matematiky, biologie, psychologie a hudební teorie. Tím jsem objevil svou největší vášeň – prozkoumávání interdisciplinárního vztahu a možností přírodních věd a umění.",
          "Rok jsem studoval obor Molekulární biologie a biochemie organismů na Karlově univerzitě v Praze. Následně jsem studium přerušil a přestěhoval se zpět do Plzně, kde nyní pracuji jako grafik."
        ]
      },
      contact: {
        title: "Kontakt",
        description: "Spojení je možné"
      }
    },
    sectionPages: {
      "volna-tvorba": {
        metaTitle: "Volná tvorba | Vojta Maur",
        metaDescription: "Seznam článků v sekci Volná tvorba.",
        title: "Volná tvorba",
        intro: "Umění je nejvyšší formou naděje (Documenta 7)"
      },
      vystavy: {
        metaTitle: "Výstavy | Vojta Maur",
        metaDescription: "Seznam článků v sekci Výstavy.",
        title: "Výstavy",
        intro: "Když mě někdo omylem vypustí z ohrádky, vznikne tohle"
      },
      cestovani: {
        metaTitle: "Cestování | Vojta Maur",
        metaDescription: "Seznam článků v sekci Cestování.",
        title: "Cestování",
        intro: "Respektuji místní zvyky a tradice"
      }
    }
  },
  en: {
    siteTitle: "Vojta Maur",
    motto: "Creating is my basic instinct",
    showAll: "Show all",
    sections: {
      "volna-tvorba": "Personal Work",
      vystavy: "Exhibitions",
      cestovani: "Travel",
      videos: "Promotional Videos"
    },
    home: {
      metaTitle: "Vojta Maur",
      metaDescription: "Personal website of Vojta Maur",
      sections: {
        "volna-tvorba": {
          title: "Personal Work",
          description: "Art is the highest form of hope (Documenta 7)"
        },
        vystavy: {
          title: "Exhibitions",
          description: "When someone accidentally lets me out of the enclosure, this is what happens"
        },
        cestovani: {
          title: "Travel",
          description: "I respect local customs and traditions"
        },
        videos: {
          title: "Promotional Videos",
          description: "Galleries are the showcase of my work... even when someone else is exhibiting..."
        }
      },
      about: {
        title: "About Me",
        description: "I play with systems and structures where the human is neither the center nor the goal",
        embedTitle: "3D head scan",
        paragraphs: [
          "From an early age, I was interested in art. For three years I attended an elementary art school, where I became familiar with various traditional visual art techniques. I have always been fascinated by computers, so I began teaching myself to work in 2D and 3D software. Even before finishing elementary school, I also started filming documentary videos from every opening at the Gallery of the City of Pilsen. I ended my collaboration with that gallery after three years, at the moment when I was asked to include a statement from Martin Baxa in a video after he attended an opening. I commented on the situation with the sentence: “I document art, not politicians!”",
          "I studied Multimedia Production at the Secondary School of Trade, Applied Art and Design in Pilsen. This not particularly demanding school gave me enough time and space to study seemingly unrelated disciplines, especially programming, mathematics, biology, psychology, and music theory. Through that, I discovered my greatest passion: exploring the interdisciplinary relationship and possibilities of the natural sciences and art.",
          "I studied Molecular Biology and Biochemistry of Organisms for one year at Charles University in Prague. I then interrupted my studies and moved back to Pilsen, where I now work as a graphic designer."
        ]
      },
      contact: {
        title: "Contact",
        description: "Connection is possible"
      }
    },
    sectionPages: {
      "volna-tvorba": {
        metaTitle: "Personal Work | Vojta Maur",
        metaDescription: "List of articles in the Personal Work section.",
        title: "Personal Work",
        intro: "Art is the highest form of hope (Documenta 7)"
      },
      vystavy: {
        metaTitle: "Exhibitions | Vojta Maur",
        metaDescription: "List of articles in the Exhibitions section.",
        title: "Exhibitions",
        intro: "When someone accidentally lets me out of the enclosure, this is what happens"
      },
      cestovani: {
        metaTitle: "Travel | Vojta Maur",
        metaDescription: "List of articles in the Travel section.",
        title: "Travel",
        intro: "I respect local customs and traditions"
      }
    }
  }
} as const;

export function localizePath(pathname: string, lang: Lang): string {
  const clean = pathname.startsWith("/") ? pathname : `/${pathname}`;
  if (lang === "cs") return clean.replace(/^\/en(?=\/|$)/, "") || "/";
  if (clean === "/") return "/en/";
  if (clean.startsWith("/en/")) return clean;
  return `/en${clean}`.replace(/\/+/g, "/");
}

export function canonicalPostPath(slug: string, lang: Lang): string {
  return lang === "en" ? `/en/${slug}/` : `/${slug}/`;
}

export function canonicalSectionPath(sectionId: SectionId, lang: Lang): string {
  return lang === "en" ? `/en/${sectionId}/` : `/${sectionId}/`;
}

export function canonicalHomePath(lang: Lang): string {
  return lang === "en" ? "/en/" : "/";
}

export function formatMonthYear(input: string | Date, lang: Lang): string {
  const date = input instanceof Date ? input : new Date(input);
  const locale = lang === "en" ? "en-US" : "cs-CZ";
  return new Intl.DateTimeFormat(locale, {
    month: "long",
    year: "numeric"
  }).format(date);
}

export function formatDateRange(dateFrom: string | Date, dateTo: string | Date | undefined, lang: Lang): string {
  const locale = lang === "en" ? "en-US" : "cs-CZ";
  const formatter = new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "long",
    year: "numeric"
  });

  const from = dateFrom instanceof Date ? dateFrom : new Date(dateFrom);
  if (!dateTo) return formatter.format(from);

  const to = dateTo instanceof Date ? dateTo : new Date(dateTo);
  return `${formatter.format(from)} – ${formatter.format(to)}`;
}
