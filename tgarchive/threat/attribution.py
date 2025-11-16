"""
Attribution Engine for Threat Actor Identification

Cross-platform identity correlation and behavioral analysis:
- Writing style analysis (stylometry)
- Operational pattern matching
- Tool/technique fingerprinting
- Cross-account correlation
- AI-generated content detection

Author: SPECTRA Intelligence System
"""

import re
import logging
from typing import List, Dict, Optional, Tuple, Set
from collections import Counter, defaultdict
import statistics

logger = logging.getLogger(__name__)

# Optional: langdetect for language detection
try:
    from langdetect import detect, detect_langs
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False
    logger.warning("langdetect not available. Install with: pip install langdetect")


class WritingStyleProfile:
    """Profile of an actor's writing style."""

    def __init__(self):
        self.vocabulary_size: int = 0
        self.avg_sentence_length: float = 0.0
        self.avg_word_length: float = 0.0
        self.punctuation_density: float = 0.0
        self.emoji_density: float = 0.0
        self.technical_density: float = 0.0
        self.uppercase_ratio: float = 0.0
        self.language: str = "unknown"
        self.proficiency_level: str = "unknown"
        self.common_words: List[str] = []
        self.common_bigrams: List[Tuple[str, str]] = []

    def to_vector(self) -> List[float]:
        """Convert profile to feature vector for similarity comparison."""
        return [
            float(self.vocabulary_size),
            self.avg_sentence_length,
            self.avg_word_length,
            self.punctuation_density,
            self.emoji_density,
            self.technical_density,
            self.uppercase_ratio
        ]


class AttributionEngine:
    """
    Cross-platform identity correlation and attribution.

    Identifies actors using multiple signals:
    - Writing style (stylometry)
    - Operational patterns
    - Tool fingerprints
    - Behavioral signatures
    """

    def __init__(self):
        self.technical_terms = self._load_technical_terms()
        self.tool_patterns = self._load_tool_patterns()

    def _load_technical_terms(self) -> Set[str]:
        """Load list of technical/security terms."""
        return {
            # Programming/scripting
            "python", "bash", "powershell", "javascript", "php", "ruby", "perl",
            "sql", "nosql", "api", "rest", "json", "xml", "yaml",

            # Security tools
            "metasploit", "burp", "nmap", "wireshark", "sqlmap", "hydra",
            "hashcat", "john", "aircrack", "nikto", "gobuster", "dirbuster",

            # Exploitation
            "exploit", "payload", "shellcode", "reverse", "shell", "backdoor",
            "rootkit", "trojan", "rat", "botnet", "c2", "c&c",

            # Techniques
            "injection", "xss", "csrf", "sqli", "rce", "lfi", "rfi",
            "privesc", "enumeration", "reconnaissance", "lateral",

            # Cryptography
            "encryption", "decryption", "cipher", "hash", "md5", "sha256",
            "aes", "rsa", "pgp", "gpg", "ssl", "tls",

            # Network
            "vpn", "proxy", "tor", "i2p", "onion", "darknet", "clearnet",
            "dns", "tcp", "udp", "icmp", "ssh", "ftp", "http", "https"
        }

    def _load_tool_patterns(self) -> Dict[str, List[str]]:
        """Load patterns for tool fingerprinting."""
        return {
            "Metasploit": [
                r"msfconsole",
                r"meterpreter",
                r"exploit/\w+/\w+",
                r"payload/\w+/\w+",
                r"set RHOST",
                r"set LHOST"
            ],
            "Cobalt Strike": [
                r"beacon",
                r"malleable profile",
                r"powershell.*-nop",
                r"spawn",
                r"inject"
            ],
            "Empire": [
                r"invoke-empire",
                r"stager",
                r"launcher",
                r"usestager"
            ],
            "Mimikatz": [
                r"mimikatz",
                r"sekurlsa::logonpasswords",
                r"lsadump",
                r"kerberos::golden"
            ],
            "Nmap": [
                r"nmap\s+-",
                r"-sS\s",
                r"-sV\s",
                r"-p\s*\d+"
            ],
            "SQLmap": [
                r"sqlmap",
                r"--dbs",
                r"--tables",
                r"--dump"
            ]
        }

    def analyze_writing_style(self, messages: List[Dict]) -> WritingStyleProfile:
        """
        Stylometric analysis for author attribution.

        Analyzes:
        - Vocabulary richness
        - Sentence structure
        - Punctuation patterns
        - Emoji usage
        - Technical jargon density
        - Language proficiency

        Args:
            messages: List of message dicts with 'text' field

        Returns:
            WritingStyleProfile
        """
        profile = WritingStyleProfile()

        # Extract all text
        texts = [msg.get('text', '') for msg in messages if msg.get('text')]
        if not texts:
            return profile

        corpus = " ".join(texts)

        # Vocabulary analysis
        words = self._extract_words(corpus)
        profile.vocabulary_size = len(set(words))
        profile.common_words = [word for word, count in Counter(words).most_common(20)]

        # Bigrams
        bigrams = list(zip(words[:-1], words[1:]))
        profile.common_bigrams = [bg for bg, count in Counter(bigrams).most_common(10)]

        # Sentence analysis
        sentences = self._split_sentences(corpus)
        if sentences:
            sentence_lengths = [len(s.split()) for s in sentences]
            profile.avg_sentence_length = statistics.mean(sentence_lengths)

        # Word length
        if words:
            profile.avg_word_length = statistics.mean(len(w) for w in words)

        # Punctuation density
        punct_count = len(re.findall(r'[!?.,;:]', corpus))
        profile.punctuation_density = punct_count / len(corpus) if corpus else 0

        # Emoji density
        emoji_count = len(re.findall(r'[\U0001F300-\U0001F9FF]', corpus))
        profile.emoji_density = emoji_count / len(corpus) if corpus else 0

        # Technical jargon
        technical_count = sum(1 for w in words if w.lower() in self.technical_terms)
        profile.technical_density = technical_count / len(words) if words else 0

        # Uppercase ratio
        uppercase_count = sum(1 for c in corpus if c.isupper())
        profile.uppercase_ratio = uppercase_count / len(corpus) if corpus else 0

        # Language detection
        if LANGDETECT_AVAILABLE and corpus:
            try:
                profile.language = detect(corpus)
            except:
                profile.language = "unknown"
        else:
            profile.language = "unknown"

        # Proficiency assessment (simple heuristic)
        profile.proficiency_level = self._assess_proficiency(profile)

        return profile

    def _extract_words(self, text: str) -> List[str]:
        """Extract words from text (alphanumeric tokens)."""
        return re.findall(r'\b\w+\b', text.lower())

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        # Simple sentence splitter
        sentences = re.split(r'[.!?]+', text)
        return [s.strip() for s in sentences if s.strip()]

    def _assess_proficiency(self, profile: WritingStyleProfile) -> str:
        """
        Assess language proficiency level.

        Based on:
        - Vocabulary richness
        - Sentence complexity
        - Error patterns
        """
        if profile.vocabulary_size > 1000:
            return "advanced"
        elif profile.vocabulary_size > 500:
            return "intermediate"
        elif profile.vocabulary_size > 200:
            return "basic"
        else:
            return "beginner"

    def find_similar_actors_by_style(
        self,
        target_profile: WritingStyleProfile,
        candidate_profiles: Dict[int, WritingStyleProfile],
        threshold: float = 0.8
    ) -> List[Tuple[int, float]]:
        """
        Find actors with similar writing style.

        Could indicate:
        - Same person with multiple accounts
        - Coordinated group with shared training
        - AI-generated content (uniform style)

        Args:
            target_profile: Profile to match against
            candidate_profiles: Dict mapping user_id to their profile
            threshold: Minimum similarity score (0-1)

        Returns:
            List of (user_id, similarity_score) tuples, sorted by similarity
        """
        target_vector = target_profile.to_vector()

        similarities = []
        for user_id, candidate_profile in candidate_profiles.items():
            candidate_vector = candidate_profile.to_vector()

            # Cosine similarity
            similarity = self._cosine_similarity(target_vector, candidate_vector)

            if similarity >= threshold:
                similarities.append((user_id, similarity))

        return sorted(similarities, key=lambda x: x[1], reverse=True)

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if len(vec1) != len(vec2):
            return 0.0

        # Normalize vectors
        import math

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = math.sqrt(sum(a * a for a in vec1))
        magnitude2 = math.sqrt(sum(b * b for b in vec2))

        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0

        return dot_product / (magnitude1 * magnitude2)

    def detect_tool_fingerprints(self, messages: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Identify tools/frameworks used by actor.

        Detects:
        - Metasploit (specific syntax patterns)
        - Cobalt Strike (beacon configurations)
        - Empire (PowerShell commands)
        - Mimikatz (credential dumping)
        - And more...

        Args:
            messages: List of message dicts

        Returns:
            Dict mapping tool name to list of matching evidence
        """
        tool_matches = defaultdict(list)

        for msg in messages:
            text = msg.get('text', '')
            if not text:
                continue

            # Check each tool's patterns
            for tool_name, patterns in self.tool_patterns.items():
                for pattern in patterns:
                    matches = re.findall(pattern, text, re.IGNORECASE)
                    if matches:
                        tool_matches[tool_name].append({
                            "message_id": msg.get('id'),
                            "matched_pattern": pattern,
                            "matches": matches,
                            "context": text[:200]  # First 200 chars for context
                        })

        return dict(tool_matches)

    def detect_operational_patterns(self, messages: List[Dict]) -> Dict[str, any]:
        """
        Identify operational patterns and TTPs.

        Patterns:
        - Reconnaissance → Exploitation → Post-exploitation sequence
        - Specific attack chains
        - Operational security practices

        Args:
            messages: List of messages (chronologically sorted)

        Returns:
            Dict with detected patterns
        """
        patterns = {
            "reconnaissance": [],
            "exploitation": [],
            "post_exploitation": [],
            "opsec_indicators": [],
            "attack_chains": []
        }

        # Keywords for each phase
        recon_keywords = {"nmap", "scan", "enumerate", "reconnaissance", "osint", "footprint"}
        exploit_keywords = {"exploit", "vulnerability", "cve", "rce", "injection", "payload"}
        post_exploit_keywords = {"privilege", "escalation", "lateral", "persistence", "exfiltration"}
        opsec_keywords = {"vpn", "proxy", "tor", "anonymize", "obfuscate", "encode", "encrypt"}

        for msg in messages:
            text = msg.get('text', '').lower()
            words = set(self._extract_words(text))

            # Check each phase
            if words & recon_keywords:
                patterns["reconnaissance"].append(msg.get('id'))

            if words & exploit_keywords:
                patterns["exploitation"].append(msg.get('id'))

            if words & post_exploit_keywords:
                patterns["post_exploitation"].append(msg.get('id'))

            if words & opsec_keywords:
                patterns["opsec_indicators"].append(msg.get('id'))

        # Detect attack chains (recon → exploit → post-exploit)
        if patterns["reconnaissance"] and patterns["exploitation"]:
            if patterns["post_exploitation"]:
                patterns["attack_chains"].append({
                    "type": "full_kill_chain",
                    "stages": ["reconnaissance", "exploitation", "post_exploitation"]
                })
            else:
                patterns["attack_chains"].append({
                    "type": "partial_kill_chain",
                    "stages": ["reconnaissance", "exploitation"]
                })

        return patterns

    def detect_ai_generated_content(self, messages: List[Dict]) -> Dict[str, any]:
        """
        Detect potential AI-generated content.

        Indicators:
        - Unusually consistent writing style
        - High grammatical correctness
        - Lack of informal patterns/typos
        - Repetitive phrasing

        Args:
            messages: List of messages

        Returns:
            {
                "ai_likelihood": float,  # 0-1
                "indicators": List[str],
                "confidence": float
            }
        """
        if not messages:
            return {"ai_likelihood": 0.0, "indicators": [], "confidence": 0.0}

        indicators = []
        score = 0.0

        # Analyze style consistency
        profile = self.analyze_writing_style(messages)

        # Indicator 1: Very consistent sentence length
        texts = [msg.get('text', '') for msg in messages if msg.get('text')]
        if texts:
            sentences = []
            for text in texts:
                sentences.extend(self._split_sentences(text))

            if len(sentences) > 10:
                sentence_lengths = [len(s.split()) for s in sentences]
                if statistics.stdev(sentence_lengths) < 3.0:  # Very low variance
                    indicators.append("Highly consistent sentence length")
                    score += 0.3

        # Indicator 2: Perfect grammar (low punctuation variance)
        if profile.punctuation_density > 0.05 and profile.punctuation_density < 0.15:
            indicators.append("Consistent punctuation usage")
            score += 0.2

        # Indicator 3: No informal patterns
        corpus = " ".join(texts)
        if not re.search(r'\b(lol|lmao|wtf|omg|brb|tbh|imo|afaik)\b', corpus, re.IGNORECASE):
            if len(messages) > 20:  # Significant sample
                indicators.append("Absence of informal language")
                score += 0.2

        # Indicator 4: No typos/misspellings (heuristic: repeated characters)
        typo_count = len(re.findall(r'(\w)\1{2,}', corpus))  # 3+ repeated chars
        if typo_count == 0 and len(corpus) > 1000:
            indicators.append("No apparent typos or informal spelling")
            score += 0.15

        # Indicator 5: Technical but not specialized
        if profile.technical_density > 0.05 and profile.technical_density < 0.15:
            indicators.append("Moderate technical vocabulary without deep specialization")
            score += 0.15

        ai_likelihood = min(1.0, score)
        confidence = 0.7 if len(messages) > 50 else 0.4  # More messages = higher confidence

        return {
            "ai_likelihood": round(ai_likelihood, 3),
            "indicators": indicators,
            "confidence": confidence
        }

    def correlate_accounts(
        self,
        profiles: Dict[int, WritingStyleProfile],
        min_similarity: float = 0.85
    ) -> List[List[int]]:
        """
        Identify clusters of accounts likely controlled by same actor.

        Args:
            profiles: Dict mapping user_id to WritingStyleProfile
            min_similarity: Minimum similarity to link accounts

        Returns:
            List of account clusters (each cluster is list of user_ids)
        """
        # Build similarity matrix
        user_ids = list(profiles.keys())
        clusters = []

        visited = set()

        for i, user_id in enumerate(user_ids):
            if user_id in visited:
                continue

            # Start new cluster
            cluster = [user_id]
            visited.add(user_id)

            # Find similar accounts
            profile = profiles[user_id]
            similar = self.find_similar_actors_by_style(
                profile,
                {uid: p for uid, p in profiles.items() if uid != user_id and uid not in visited},
                threshold=min_similarity
            )

            for similar_id, similarity in similar:
                cluster.append(similar_id)
                visited.add(similar_id)

            if len(cluster) > 1:
                clusters.append(cluster)

        return clusters


# Example usage
if __name__ == "__main__":
    print("=== Attribution Engine Demo ===\n")

    # Sample messages
    messages = [
        {
            "id": 1,
            "text": "Running nmap scan on target network to enumerate open ports and services."
        },
        {
            "id": 2,
            "text": "Found vulnerability CVE-2024-1234. Preparing exploit with msfconsole."
        },
        {
            "id": 3,
            "text": "Setting payload to reverse_tcp. LHOST=192.168.1.100 LPORT=4444."
        },
        {
            "id": 4,
            "text": "Shell access obtained. Attempting privilege escalation using local exploit."
        }
    ]

    engine = AttributionEngine()

    # Analyze writing style
    profile = engine.analyze_writing_style(messages)
    print("Writing Style Profile:")
    print(f"  Vocabulary size: {profile.vocabulary_size}")
    print(f"  Avg sentence length: {profile.avg_sentence_length:.1f} words")
    print(f"  Technical density: {profile.technical_density:.1%}")
    print(f"  Language: {profile.language}")
    print()

    # Detect tool fingerprints
    tools = engine.detect_tool_fingerprints(messages)
    print("Tool Fingerprints Detected:")
    for tool, matches in tools.items():
        print(f"  {tool}: {len(matches)} matches")
    print()

    # Detect operational patterns
    patterns = engine.detect_operational_patterns(messages)
    print("Operational Patterns:")
    print(f"  Reconnaissance: {len(patterns['reconnaissance'])} messages")
    print(f"  Exploitation: {len(patterns['exploitation'])} messages")
    print(f"  Attack chains: {len(patterns['attack_chains'])} detected")
    print()

    # AI content detection
    ai_detect = engine.detect_ai_generated_content(messages)
    print("AI-Generated Content Analysis:")
    print(f"  AI likelihood: {ai_detect['ai_likelihood']:.1%}")
    print(f"  Confidence: {ai_detect['confidence']:.1%}")
    print(f"  Indicators: {len(ai_detect['indicators'])}")
    print()

    print("=== Attribution demo complete! ===")
