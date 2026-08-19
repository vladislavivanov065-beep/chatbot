"""Упрощённая многопользовательская (2-8 игроков) шахматная логика.

Правила намеренно упрощены (без рокировки, взятия на проходе,
превращения пешки и без детекции шаха/мата): фигуры двигаются по
стандартным правилам, взятие короля выбывает игрока, его фигуры
остаются на доске нейтральными (без владельца).

Геометрия поля (см. обсуждение с пользователем):

    [5555555]         [8888888]
    (--буфер--)       (--буфер--)
    [7][ 3 ][ 1/2 ][ 4 ][6]
    (--буфер--)       (--буфер--)
    [7777777]         [6666666]

Игроки 1 и 2 - обычная доска 8x8 (верх/низ), с буфером в GAP0 строк
между их фигурами и ядром (CORE) в центре. Игрок 3 добавляет колонку
слева, игрок 4 - справа, с буфером в GAP клеток между ней и центром.
Игроки 5/8 (сверху) и 7/6 (снизу) - широкие горизонтальные блоки в
углах (как 1/2, ряд фигур + ряд пешек на 8 клеток), с буфером в GAP2
строк от границы центра/3/4. По ширине они перекрывают колонки
игрока 3 (или 4) и буфер между ним и центром, и ещё немного выступают
дальше наружу.
"""
import itertools

PIECE_ORDER = ['R', 'N', 'B', 'Q', 'K', 'B', 'N', 'R']

# Пустые буферы (в клетках) между зонами игроков.
GAP0 = 2  # между игроком 1/2 и ядром (CORE) в центре
GAP = 8   # между центром (1/2) и игроком 3/4
GAP2 = 2  # между угловыми игроками 5/6/7/8 и границей центра/3/4

# Колонки угловых игроков: 2 колонки игрока 3/4 плюс ещё 6 клеток дальше
# наружу - всегда ровно 8 колонок, независимо от GAP, чтобы в ряду
# помещался полный комплект фигур.
# Игроки 5 и 7 (слева) сдвинуты на 8 клеток вправо от "родной" позиции
# над/под игроком 3 - теперь они над буфером игрока 3, а не над ним самим.
LEFT_CORNER_SHIFT = 8
LEFT_CORNER_COLS = range(-8 - GAP + LEFT_CORNER_SHIFT, -GAP + LEFT_CORNER_SHIFT)
# Игроки 6 и 8 (справа) сдвинуты на 8 клеток влево - теперь над буфером
# игрока 4, а не над ним самим (симметрично левой стороне).
RIGHT_CORNER_SHIFT = -8
RIGHT_CORNER_COLS = range(8 + GAP + RIGHT_CORNER_SHIFT, 16 + GAP + RIGHT_CORNER_SHIFT)
# Игрок 4: был поднят на 2 клетки вверх, затем опущен обратно на 2 вниз -
# итог 0 (совпадает с базовой позицией относительно игрока 3).
SEAT4_ROW_SHIFT = -2 + 2
# Игрок 7: был опущен на 2 клетки вниз, затем поднят обратно на 2 вверх -
# итог 0 (совпадает с базовой позицией).
SEAT7_ROW_SHIFT = 2 - 2

# Каждая "рука" (seat) описывается тем, как строится её область:
# axis='row'  -> фигуры разложены вдоль фиксированной строки (back_row/pawn_row), колонки берутся из cols
# axis='col'  -> фигуры разложены вдоль фиксированной колонки (back_col/pawn_col), строки берутся из rows
SEAT_META = {
    1: dict(parent=None, forward=(1, 0), axis='row', back_row=0 - GAP0, pawn_row=1 - GAP0, cols=range(0, 8)),
    2: dict(parent=None, forward=(-1, 0), axis='row', back_row=7 + GAP0, pawn_row=6 + GAP0, cols=range(0, 8)),
    3: dict(parent=None, forward=(0, 1), axis='col', back_col=-2 - GAP, pawn_col=-1 - GAP, rows=range(0, 8)),
    4: dict(parent=None, forward=(0, -1), axis='col', back_col=9 + GAP, pawn_col=8 + GAP,
            rows=range(0 + SEAT4_ROW_SHIFT, 8 + SEAT4_ROW_SHIFT)),
    5: dict(parent=3, forward=(1, 0), axis='row', back_row=-2 - GAP2, pawn_row=-1 - GAP2, cols=LEFT_CORNER_COLS),
    7: dict(parent=3, forward=(-1, 0), axis='row',
            back_row=7 + 2 + GAP2 + SEAT7_ROW_SHIFT, pawn_row=7 + 1 + GAP2 + SEAT7_ROW_SHIFT, cols=LEFT_CORNER_COLS),
    6: dict(parent=4, forward=(-1, 0), axis='row', back_row=7 + 2 + GAP2, pawn_row=7 + 1 + GAP2, cols=RIGHT_CORNER_COLS),
    8: dict(parent=4, forward=(1, 0), axis='row', back_row=-2 - GAP2, pawn_row=-1 - GAP2, cols=RIGHT_CORNER_COLS),
}

CHILDREN = {sid: [c for c, m in SEAT_META.items() if m['parent'] == sid] for sid in SEAT_META}

# Ядро доски (пустая середина между рядами игрока 1 и игрока 2) - существует,
# пока в игре есть хоть один участник.
CORE = frozenset((r, c) for r in range(2, 6) for c in range(0, 8))

# Буферные (всегда пустые) клетки на стыках зон.
GAP_CELLS = {
    1: frozenset((r, c) for r in range(0, GAP0) for c in range(0, 8)),
    2: frozenset((r, c) for r in range(8 - GAP0, 8) for c in range(0, 8)),
    3: frozenset((r, c) for r in range(0, 8) for c in range(-GAP, 0)),
    4: frozenset(
        (r, c)
        for r in range(0 + SEAT4_ROW_SHIFT, 8 + SEAT4_ROW_SHIFT)
        for c in range(8, 8 + GAP)
    ),
    5: frozenset((r, c) for r in range(-GAP2, 0) for c in LEFT_CORNER_COLS),
    8: frozenset((r, c) for r in range(-GAP2, 0) for c in RIGHT_CORNER_COLS),
    7: frozenset(
        (r, c)
        for r in range(8 + SEAT7_ROW_SHIFT, 8 + GAP2 + SEAT7_ROW_SHIFT)
        for c in LEFT_CORNER_COLS
    ),
    6: frozenset((r, c) for r in range(8, 8 + GAP2) for c in RIGHT_CORNER_COLS),
}

SEAT_COLORS = {
    1: '#e63946', 2: '#457b9d', 3: '#2a9d8f', 4: '#e9c46a',
    5: '#8338ec', 6: '#fb8500', 7: '#06d6a0', 8: '#ef476f',
}

CAPTURE_POINTS = {'P': 1, 'N': 3, 'B': 3, 'R': 5, 'Q': 8, 'K': 10}

# Способности, покупаемые за очки, полученные взятием фигур.
# "shield" и "extra_turn" - мгновенные покупки, не отнимающие ход.
# Остальные заменяют собой ход целиком.
ABILITY_COSTS = {
    'shield': 10,
    'attack_through': 20,
    'skip_turn': 30,
    'fog': 40,
    'extra_turn': 50,
    'revival': 60,
    'teleport': 70,
    'freeze': 80,
    'explosion': 90,
}

TURN_CONSUMING_ABILITIES = {
    'attack_through', 'skip_turn', 'fog', 'revival', 'teleport', 'freeze', 'explosion',
}

ROOK_DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1)]
BISHOP_DIRS = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
QUEEN_DIRS = ROOK_DIRS + BISHOP_DIRS
KNIGHT_OFFSETS = [(1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2), (-2, -1)]


def build_seat_region_and_pieces(seat_id):
    meta = SEAT_META[seat_id]
    back_cells = []
    pawn_cells = []
    if meta['axis'] == 'row':
        for c in meta['cols']:
            back_cells.append((meta['back_row'], c))
            pawn_cells.append((meta['pawn_row'], c))
    else:
        for r in meta['rows']:
            back_cells.append((r, meta['back_col']))
            pawn_cells.append((r, meta['pawn_col']))
    region = set(back_cells) | set(pawn_cells) | set(GAP_CELLS.get(seat_id, ()))
    return region, back_cells, pawn_cells


class Game:
    def __init__(self):
        self.seats = {
            sid: {
                'status': 'NOT_CREATED',  # NOT_CREATED | ACTIVE | VACANT | NEUTRAL
                'token': None,
                'region': set(),
                'back_cells': [],
                'pawn_cells': [],
                'score': 0,
                'shield': False,
                'extra_turn_pending': False,
                'skip_next': False,
                'graveyard': [],  # типы своих фигур, ранее взятых кем-либо
            }
            for sid in SEAT_META
        }
        self.board = {}  # (r, c) -> {'seat': sid_or_None, 'type': letter}
        self.current_seat = None
        self.started = False
        self.finished = False
        self.winner = None
        self.players = {}  # token -> seat_id
        self.fog = None  # {'caster': sid, 'turns_left': int}
        self.frozen = None  # {'seat': sid, 'pos': (r, c)}

    # ---------- вспомогательные ----------
    def active_seats_sorted(self):
        return sorted(sid for sid, s in self.seats.items() if s['status'] == 'ACTIVE')

    def board_cells(self):
        cells = set(CORE)
        for s in self.seats.values():
            if s['status'] in ('ACTIVE', 'NEUTRAL', 'VACANT'):
                cells |= s['region']
        return cells

    def occupied_seats_count(self):
        return len(self.active_seats_sorted())

    def restart(self):
        """Начинает партию заново с тем числом игроков, что сейчас активны.

        Каждый из них заново занимает места по порядку (1, 2, 3, ...),
        со свежей доской, очками и способностями."""
        tokens_in_order = [self.seats[sid]['token'] for sid in self.active_seats_sorted()]
        self.__init__()
        for token in tokens_in_order:
            self.add_player(token)

    # ---------- присоединение / выход ----------
    def add_player(self, token):
        if self.finished:
            return None
        for sid in sorted(self.seats):
            if self.seats[sid]['status'] == 'VACANT':
                self._activate_seat(sid, token)
                return sid
        for sid in sorted(self.seats):
            if self.seats[sid]['status'] == 'NOT_CREATED':
                self._activate_seat(sid, token)
                return sid
        return None  # игра заполнена (8 игроков)

    def _activate_seat(self, sid, token):
        region, back_cells, pawn_cells = build_seat_region_and_pieces(sid)
        seat = self.seats[sid]
        seat['status'] = 'ACTIVE'
        seat['token'] = token
        seat['region'] = region
        seat['back_cells'] = back_cells
        seat['pawn_cells'] = pawn_cells
        seat['score'] = 0
        seat['shield'] = False
        seat['extra_turn_pending'] = False
        seat['skip_next'] = False
        seat['graveyard'] = []
        for pos, ptype in zip(back_cells, PIECE_ORDER):
            self.board[pos] = {'seat': sid, 'type': ptype}
        for pos in pawn_cells:
            self.board[pos] = {'seat': sid, 'type': 'P'}
        self.players[token] = sid

        if self.occupied_seats_count() >= 2:
            self.started = True
            if self.current_seat is None:
                self.current_seat = self.active_seats_sorted()[0]
        self._ensure_current_seat_valid()

    def remove_player(self, token):
        """Игрок покинул сайт: его фигуры пропадают, поле уменьшается если возможно."""
        sid = self.players.get(token)
        if sid is None:
            return
        seat = self.seats[sid]
        if seat['status'] != 'ACTIVE':
            return
        for pos in list(seat['region']):
            self.board.pop(pos, None)
        seat['status'] = 'VACANT'
        seat['token'] = None
        del self.players[token]
        if self.frozen and self.frozen['seat'] == sid:
            self.frozen = None
        self._try_shrink(sid)
        self._ensure_current_seat_valid()
        self._check_finished()

    def _try_shrink(self, sid):
        seat = self.seats[sid]
        if seat['status'] != 'VACANT':
            return
        children = CHILDREN.get(sid, [])
        if any(self.seats[c]['status'] in ('ACTIVE', 'NEUTRAL', 'VACANT') for c in children):
            return  # ещё есть "дальние" части поля - убрать эту нельзя
        seat['status'] = 'NOT_CREATED'
        seat['region'] = set()
        seat['back_cells'] = []
        seat['pawn_cells'] = []
        parent = SEAT_META[sid]['parent']
        if parent is not None:
            self._try_shrink(parent)

    def _eliminate_seat(self, sid):
        seat = self.seats[sid]
        if seat['status'] != 'ACTIVE':
            return
        seat['status'] = 'NEUTRAL'
        token = seat['token']
        seat['token'] = None
        if token in self.players:
            del self.players[token]
        for pos, piece in self.board.items():
            if piece['seat'] == sid:
                piece['seat'] = None
        if self.frozen and self.frozen['seat'] == sid:
            self.frozen = None
        self._ensure_current_seat_valid()
        self._check_finished()

    def _ensure_current_seat_valid(self):
        active = self.active_seats_sorted()
        if not active:
            self.current_seat = None
            return
        if self.current_seat not in active:
            greater = [s for s in active if s > (self.current_seat or 0)]
            self.current_seat = greater[0] if greater else active[0]

    def _check_finished(self):
        active = self.active_seats_sorted()
        if self.started and len(active) <= 1:
            self.finished = True
            self.winner = active[0] if active else None

    def advance_turn(self):
        # "Доп. ход": если он был куплен в этом ходу - не передаём ход дальше.
        if self.current_seat is not None and self.seats[self.current_seat]['extra_turn_pending']:
            self.seats[self.current_seat]['extra_turn_pending'] = False
            return

        # Снимаем заморозку сразу после того, как ход её владельца закончился.
        if self.frozen and self.frozen['seat'] == self.current_seat:
            self.frozen = None

        # Тикаем счётчик "тумана войны".
        if self.fog:
            self.fog['turns_left'] -= 1
            if self.fog['turns_left'] <= 0:
                self.fog = None

        active = self.active_seats_sorted()
        if not active:
            self.current_seat = None
            return

        if self.current_seat in active:
            idx = active.index(self.current_seat)
            rotation = active[idx + 1:] + active[:idx + 1]
        else:
            rotation = active

        for candidate in rotation:
            if self.seats[candidate]['skip_next']:
                self.seats[candidate]['skip_next'] = False
                continue
            self.current_seat = candidate
            return
        self.current_seat = rotation[0]

    # ---------- движение фигур ----------
    def legal_moves(self, pos):
        piece = self.board.get(pos)
        if not piece:
            return []
        seat = piece['seat']
        ptype = piece['type']
        if self.frozen and self.frozen['pos'] == pos and self.frozen['seat'] == seat:
            return []
        cells = self.board_cells()
        moves = []

        if ptype == 'P':
            if seat is None:
                return []
            meta = SEAT_META[seat]
            fwd = meta['forward']
            one = (pos[0] + fwd[0], pos[1] + fwd[1])
            if one in cells and self.board.get(one) is None:
                moves.append(one)
                if pos in self.seats[seat]['pawn_cells']:
                    two = (pos[0] + 2 * fwd[0], pos[1] + 2 * fwd[1])
                    if two in cells and self.board.get(two) is None:
                        moves.append(two)
            perp = [(-fwd[1], fwd[0]), (fwd[1], -fwd[0])]
            for pd in perp:
                cap = (pos[0] + fwd[0] + pd[0], pos[1] + fwd[1] + pd[1])
                if cap in cells:
                    target = self.board.get(cap)
                    if target is not None and target['seat'] != seat:
                        moves.append(cap)
        elif ptype == 'N':
            for dr, dc in KNIGHT_OFFSETS:
                t = (pos[0] + dr, pos[1] + dc)
                if t in cells:
                    occ = self.board.get(t)
                    if occ is None or occ['seat'] != seat:
                        moves.append(t)
        elif ptype == 'K':
            for dr, dc in QUEEN_DIRS:
                t = (pos[0] + dr, pos[1] + dc)
                if t in cells:
                    occ = self.board.get(t)
                    if occ is None or occ['seat'] != seat:
                        moves.append(t)
        else:
            dirs = ROOK_DIRS if ptype == 'R' else BISHOP_DIRS if ptype == 'B' else QUEEN_DIRS
            for dr, dc in dirs:
                r, c = pos
                while True:
                    r += dr
                    c += dc
                    if (r, c) not in cells:
                        break
                    occ = self.board.get((r, c))
                    if occ is None:
                        moves.append((r, c))
                        continue
                    if occ['seat'] != seat:
                        moves.append((r, c))
                    break
        return moves

    def attack_through_targets(self, pos):
        """Клетки, куда можно ударить "через одну фигуру" способностью attack_through."""
        piece = self.board.get(pos)
        if not piece or piece['type'] not in ('R', 'B', 'Q'):
            return []
        seat = piece['seat']
        cells = self.board_cells()
        dirs = ROOK_DIRS if piece['type'] == 'R' else BISHOP_DIRS if piece['type'] == 'B' else QUEEN_DIRS
        targets = []
        for dr, dc in dirs:
            r, c = pos
            blocker_found = False
            while True:
                r += dr
                c += dc
                if (r, c) not in cells:
                    break
                occ = self.board.get((r, c))
                if not blocker_found:
                    if occ is not None:
                        blocker_found = True
                    continue
                if occ is not None and occ['seat'] != seat:
                    targets.append((r, c))
                break
        return targets

    def _shield_blocks(self, captured):
        return bool(
            captured and captured['type'] == 'K' and captured['seat'] is not None
            and self.seats[captured['seat']]['shield']
        )

    def _apply_capture(self, actor_sid, pos, captured):
        if not captured:
            return
        if captured['seat'] != actor_sid:
            self.seats[actor_sid]['score'] += CAPTURE_POINTS.get(captured['type'], 0)
        if captured['seat'] is not None:
            self.seats[captured['seat']]['graveyard'].append(captured['type'])
        if self.frozen and self.frozen['pos'] == pos:
            self.frozen = None

    def make_move(self, token, frm, to):
        frm = tuple(frm)
        to = tuple(to)
        if self.finished or not self.started:
            return False, 'Игра ещё не идёт'
        sid = self.players.get(token)
        if sid is None:
            return False, 'Вы не участвуете в игре'
        if sid != self.current_seat:
            return False, 'Сейчас не ваш ход'
        piece = self.board.get(frm)
        if not piece or piece['seat'] != sid:
            return False, 'Это не ваша фигура'
        if self.frozen and self.frozen['pos'] == frm and self.frozen['seat'] == sid:
            return False, 'Эта фигура заморожена и не может ходить'
        if to not in self.legal_moves(frm):
            return False, 'Недопустимый ход'

        captured = self.board.get(to)
        if self._shield_blocks(captured):
            self.seats[captured['seat']]['shield'] = False
            return False, 'Король соперника защищён щитом! Щит разрушен, выберите другой ход.'

        self.board[to] = self.board.pop(frm)
        self._apply_capture(sid, to, captured)
        if captured and captured['type'] == 'K' and captured['seat'] is not None:
            self._eliminate_seat(captured['seat'])

        if not self.finished:
            self.advance_turn()
        return True, None

    # ---------- способности ----------
    def use_ability(self, token, ability, params):
        params = params or {}
        if ability not in ABILITY_COSTS:
            return False, 'Неизвестная способность'
        if self.finished or not self.started:
            return False, 'Игра ещё не идёт'
        sid = self.players.get(token)
        if sid is None:
            return False, 'Вы не участвуете в игре'
        if ability in TURN_CONSUMING_ABILITIES and sid != self.current_seat:
            return False, 'Сейчас не ваш ход'
        cost = ABILITY_COSTS[ability]
        if self.seats[sid]['score'] < cost:
            return False, 'Недостаточно очков'

        if ability == 'shield':
            if self.seats[sid]['shield']:
                return False, 'Щит уже активен'
            ok, err = True, None
        elif ability == 'extra_turn':
            if self.seats[sid]['extra_turn_pending']:
                return False, 'Дополнительный ход уже ожидает'
            ok, err = True, None
        elif ability == 'attack_through':
            ok, err = self._do_attack_through(sid, params)
        elif ability == 'skip_turn':
            ok, err = self._do_skip_turn(sid, params)
        elif ability == 'fog':
            ok, err = self._do_fog(sid, params)
        elif ability == 'revival':
            ok, err = self._do_revival(sid, params)
        elif ability == 'teleport':
            ok, err = self._do_teleport(sid, params)
        elif ability == 'freeze':
            ok, err = self._do_freeze(sid, params)
        elif ability == 'explosion':
            ok, err = self._do_explosion(sid, params)
        else:
            ok, err = False, 'Не реализовано'

        if not ok:
            return False, err

        self.seats[sid]['score'] -= cost
        if ability == 'shield':
            self.seats[sid]['shield'] = True
        elif ability == 'extra_turn':
            self.seats[sid]['extra_turn_pending'] = True

        if ability in TURN_CONSUMING_ABILITIES and not self.finished:
            self.advance_turn()
        return True, None

    def _do_attack_through(self, sid, params):
        try:
            frm = tuple(params.get('from'))
            to = tuple(params.get('to'))
        except (TypeError, ValueError):
            return False, 'Не указаны координаты'
        piece = self.board.get(frm)
        if not piece or piece['seat'] != sid or piece['type'] not in ('R', 'B', 'Q'):
            return False, 'Нужно выбрать свою ладью, слона или ферзя'
        if to not in self.attack_through_targets(frm):
            return False, 'Недопустимая цель для удара через фигуру'
        captured = self.board.get(to)
        if self._shield_blocks(captured):
            self.seats[captured['seat']]['shield'] = False
            return False, 'Король соперника защищён щитом! Щит разрушен.'
        self.board[to] = self.board.pop(frm)
        self._apply_capture(sid, to, captured)
        if captured and captured['type'] == 'K' and captured['seat'] is not None:
            self._eliminate_seat(captured['seat'])
        return True, None

    def _do_skip_turn(self, sid, params):
        try:
            target = int(params.get('target_seat'))
        except (TypeError, ValueError):
            return False, 'Не указан игрок'
        if target not in self.seats or self.seats[target]['status'] != 'ACTIVE':
            return False, 'Этот игрок сейчас не в игре'
        self.seats[target]['skip_next'] = True
        return True, None

    def _do_fog(self, sid, params):
        self.fog = {'caster': sid, 'turns_left': self.occupied_seats_count() * 2}
        return True, None

    def _do_revival(self, sid, params):
        try:
            to = tuple(params.get('to'))
        except (TypeError, ValueError):
            return False, 'Не указана клетка'
        if 'P' not in self.seats[sid]['graveyard']:
            return False, 'Нет взятых пешек для воскрешения'
        home = set(self.seats[sid]['back_cells']) | set(self.seats[sid]['pawn_cells'])
        if to not in home or self.board.get(to) is not None:
            return False, 'Нужна свободная клетка в вашей стартовой зоне'
        self.seats[sid]['graveyard'].remove('P')
        self.board[to] = {'seat': sid, 'type': 'P'}
        return True, None

    def _do_teleport(self, sid, params):
        try:
            frm = tuple(params.get('from'))
            to = tuple(params.get('to'))
        except (TypeError, ValueError):
            return False, 'Не указаны координаты'
        piece = self.board.get(frm)
        if not piece or piece['seat'] != sid:
            return False, 'Это не ваша фигура'
        if to not in self.board_cells() or self.board.get(to) is not None:
            return False, 'Нужна свободная клетка'
        self.board[to] = self.board.pop(frm)
        return True, None

    def _do_freeze(self, sid, params):
        try:
            pos = tuple(params.get('pos'))
        except (TypeError, ValueError):
            return False, 'Не указана клетка'
        piece = self.board.get(pos)
        if not piece or piece['seat'] is None or piece['seat'] == sid:
            return False, 'Нужно выбрать вражескую фигуру'
        if self.seats[piece['seat']]['status'] != 'ACTIVE':
            return False, 'Эта фигура сейчас ничья'
        self.frozen = {'seat': piece['seat'], 'pos': pos}
        return True, None

    def _do_explosion(self, sid, params):
        try:
            center = tuple(params.get('center'))
        except (TypeError, ValueError):
            return False, 'Не указана точка'
        cells = self.board_cells()
        if center not in cells:
            return False, 'Точка вне поля'
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                pos = (center[0] + dr, center[1] + dc)
                if pos not in cells:
                    continue
                piece = self.board.get(pos)
                if piece is None or piece['type'] == 'K':
                    continue
                del self.board[pos]
                self._apply_capture(sid, pos, piece)
        return True, None

    def _visible_cells_for_seat(self, seat_id):
        """Клетки, видимые игроку seat_id, пока действует чужой "туман войны"."""
        own_region = self.seats[seat_id]['region']
        visible = set(own_region)
        own_piece_positions = [pos for pos, p in self.board.items() if p['seat'] == seat_id]
        for (pr, pc) in own_piece_positions:
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    n = (pr + dr, pc + dc)
                    if n in self.board:
                        visible.add(n)
        return visible

    # ---------- сериализация состояния ----------
    def state_for(self, token):
        my_seat = self.players.get(token)
        cells = sorted(self.board_cells())

        fogged = self.fog is not None and my_seat is not None and self.fog['caster'] != my_seat
        if fogged:
            visible = self._visible_cells_for_seat(my_seat)
            pieces = [
                {'r': r, 'c': c, 'type': p['type'], 'seat': p['seat']}
                for (r, c), p in self.board.items()
                if (r, c) in visible
            ]
        else:
            pieces = [
                {'r': r, 'c': c, 'type': p['type'], 'seat': p['seat']}
                for (r, c), p in self.board.items()
            ]

        seats_info = {}
        for sid, s in self.seats.items():
            seats_info[sid] = {
                'status': s['status'],
                'color': SEAT_COLORS[sid],
                'is_you': (sid == my_seat),
            }

        my = self.seats[my_seat] if my_seat is not None else None
        return {
            'cells': cells,
            'pieces': pieces,
            'seats': seats_info,
            'current_seat': self.current_seat,
            'my_seat': my_seat,
            'my_score': my['score'] if my else None,
            'my_shield': my['shield'] if my else False,
            'my_extra_turn_pending': my['extra_turn_pending'] if my else False,
            'my_revivable_pawns': my['graveyard'].count('P') if my else 0,
            'my_home_cells': [list(c) for c in (my['back_cells'] + my['pawn_cells'])] if my else [],
            'my_piece_frozen_pos': list(self.frozen['pos']) if (
                self.frozen and my_seat is not None and self.frozen['seat'] == my_seat
            ) else None,
            'fog_active_for_me': fogged,
            'fog_active': self.fog is not None,
            'ability_costs': ABILITY_COSTS,
            'started': self.started,
            'finished': self.finished,
            'winner': self.winner,
            'players_count': self.occupied_seats_count(),
        }
